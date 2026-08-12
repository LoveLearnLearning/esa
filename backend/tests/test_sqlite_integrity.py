import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.core.stores.chat_store import ChatStore
from backend.core.stores.conversation_summary_store import ConversationSummaryStore
from backend.core.stores.group_store import GroupStore
from backend.core.stores.migrations import run_migrations
from backend.core.stores.profile_store import ProfileStore
from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_store import UserStore
from backend.core.stores.user_presence_store import UserPresenceStore
from backend.core.utils.models import SessionPrincipal, UserRecord


def _user(user_id: str = "u1") -> UserRecord:
    return UserRecord(
        id=user_id,
        username=user_id,
        password_hash="hash",
        status="active",
    )


def _stores(database_path):
    user_store = UserStore(database_path)
    group_store = GroupStore(database_path)
    chat_store = ChatStore(database_path)
    session_store = SessionStore(database_path)
    profile_store = ProfileStore(database_path)
    run_migrations(database_path)
    return user_store, group_store, chat_store, session_store, profile_store


def test_every_project_connection_enables_foreign_keys(tmp_path):
    store = UserStore(tmp_path / "users.db")

    assert store.query_one("PRAGMA foreign_keys")[0] == 1
    assert store.query_one("PRAGMA busy_timeout")[0] == 30000


def test_owned_tables_reject_orphan_records(tmp_path):
    database_path = tmp_path / "users.db"
    user_store, group_store, chat_store, session_store, profile_store = _stores(
        database_path
    )
    assert user_store.create(_user())

    with pytest.raises(sqlite3.IntegrityError):
        group_store.create_group("missing-user", "孤儿分组")

    with pytest.raises(sqlite3.IntegrityError):
        chat_store.create_conversation("missing-user")

    with pytest.raises(sqlite3.IntegrityError):
        session_store.create(
            SessionPrincipal(
                session_id="orphan-session",
                user_id="missing-user",
            )
        )

    with pytest.raises(sqlite3.IntegrityError):
        profile_store.upsert_dimension(
            user_id="missing-user",
            field_key="preferred_language",
            value="Python",
            origin="inferred_pattern",
            confidence=0.8,
        )

    with pytest.raises(sqlite3.IntegrityError):
        profile_store.execute(
            """
            INSERT INTO profile_audit_log (
                audit_id, user_id, action, actor, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("a1", "missing-user", "test", "system", datetime.now().isoformat()),
        )


def test_user_delete_cascades_all_main_database_records(tmp_path):
    database_path = tmp_path / "users.db"
    user_store, group_store, chat_store, session_store, profile_store = _stores(
        database_path
    )
    assert user_store.create(_user())

    group = group_store.create_group("u1", "算法")
    assert group is not None
    conversation = chat_store.create_conversation(
        "u1",
        group_id=group["group_id"],
    )
    chat_store.append_messages(
        conversation["conversation_id"],
        [{"role": "user", "content": "hello"}],
    )
    session_store.create(
        SessionPrincipal(
            session_id="s1",
            user_id="u1",
            issued_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    )
    profile_store.upsert_dimension(
        user_id="u1",
        field_key="preferred_language",
        value="Python",
        origin="inferred_pattern",
        confidence=0.8,
    )
    profile_store.execute(
        """
        INSERT INTO profile_audit_log (
            audit_id, user_id, action, actor, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        ("a1", "u1", "test", "system", datetime.now().isoformat()),
    )
    profile_store.get_next_profile_version("u1")
    chat_store.execute(
        """
        INSERT INTO conversation_turn_leases (
            conversation_id, owner_token, acquired_at, expires_at
        ) VALUES (?, ?, ?, ?)
        """,
        (
            conversation["conversation_id"],
            "token",
            datetime.now(timezone.utc).isoformat(),
            (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        ),
    )
    UserPresenceStore(database_path).mark_online("u1")
    ConversationSummaryStore(database_path).upsert(
        conversation_id=conversation["conversation_id"],
        summarized_through_message_id=1,
        summary="older context",
        source_message_count=1,
    )

    user_store.execute("DELETE FROM users WHERE id = ?", ("u1",))

    for table in (
        "sessions",
        "groups",
        "conversations",
        "messages",
        "user_profile_dimensions",
        "profile_audit_log",
        "profile_versions",
        "conversation_turn_leases",
        "user_presence",
        "conversation_summaries",
    ):
        assert user_store.query_one(f"SELECT COUNT(*) FROM {table}")[0] == 0


def test_conversation_group_must_belong_to_same_user(tmp_path):
    database_path = tmp_path / "users.db"
    user_store, group_store, chat_store, _, _ = _stores(database_path)
    assert user_store.create(_user("u1"))
    assert user_store.create(_user("u2"))
    foreign_group = group_store.create_group("u2", "私有分组")
    assert foreign_group is not None

    with pytest.raises(sqlite3.IntegrityError):
        chat_store.create_conversation(
            "u1",
            group_id=foreign_group["group_id"],
        )


def test_legacy_migration_quarantines_orphans_and_preserves_valid_rows(tmp_path):
    database_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE users (id TEXT PRIMARY KEY);
        INSERT INTO users(id) VALUES ('u1');

        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE groups (
            group_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            custom_instruction TEXT NOT NULL DEFAULT '',
            style TEXT,
            tone TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE conversations (
            conversation_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            group_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            name TEXT,
            is_visible INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        INSERT INTO groups VALUES (
            'g1', 'u1', '算法', '', '', NULL, NULL, 'now', 'now'
        );
        INSERT INTO conversations VALUES (
            'c1', 'u1', '合法对话', 'g1', 'now', 'now'
        );
        INSERT INTO messages VALUES (
            1, 'c1', 'user', '保留我', NULL, 1, 'now'
        );
        INSERT INTO messages VALUES (
            2, 'missing-conversation', 'assistant', '隔离我', NULL, 1, 'now'
        );
        """
    )
    connection.commit()
    connection.close()

    # 真实启动顺序会先初始化 ChatStore，因此旧库在 V5 执行前已经存在
    # 引用 groups 的归属触发器。迁移必须能安全拆除并重建它们。
    ChatStore(database_path)

    assert run_migrations(database_path) == 10
    assert run_migrations(database_path) == 0

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT content FROM messages ORDER BY id"
        ).fetchall() == [("保留我",)]
        quarantined = connection.execute(
            """
            SELECT source_table, source_key, reason
            FROM migration_orphans
            WHERE source_table = 'messages'
            """
        ).fetchall()
        assert quarantined == [
            (
                "messages",
                "id=2",
                "missing conversations.conversation_id",
            )
        ]

        foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(messages)"
        ).fetchall()
        assert any(
            row[2] == "conversations" and row[3] == "conversation_id"
            for row in foreign_keys
        )
    finally:
        connection.close()


def test_v10_repairs_databases_that_already_recorded_a_conflicting_v9(tmp_path):
    database_path = tmp_path / "v9-collision.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE TABLE conversations (
            conversation_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            group_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT
        );
        """
    )
    connection.executemany(
        "INSERT INTO schema_migrations VALUES (?, 'now', 'legacy')",
        [(version,) for version in range(1, 10)],
    )
    connection.commit()
    connection.close()

    assert run_migrations(database_path) == 1
    connection = sqlite3.connect(database_path)
    try:
        user_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(users)")
        }
        conversation_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(conversations)")
        }
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"email", "email_verified_at", "account_role"} <= user_columns
        assert {"workspace_type", "research_project_id"} <= conversation_columns
        assert {
            "research_projects",
            "research_frontier_jobs",
            "research_documents",
            "research_datasets",
            "research_analysis_jobs",
            "email_verification_codes",
        } <= tables
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
