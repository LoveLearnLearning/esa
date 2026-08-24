# backend/core/stores/migrations.py

"""SQLite schema migrations used by the backend stores."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from backend.core.stores.sqlite_connection import connect_sqlite

logger = logging.getLogger(__name__)

MigrationAction = list[str] | Callable[[sqlite3.Connection], None]
MigrationDef = tuple[int, str, MigrationAction]


SESSIONS_DDL = """
CREATE TABLE {table} (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
)
"""

GROUPS_DDL = """
CREATE TABLE {table} (
    group_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    custom_instruction TEXT NOT NULL DEFAULT '',
    style TEXT,
    tone TEXT,
    project_id TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
)
"""

CONVERSATIONS_DDL = """
CREATE TABLE {table} (
    conversation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    group_id TEXT,
    workspace_type TEXT NOT NULL DEFAULT 'learning',
    research_project_id TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(group_id) REFERENCES groups(group_id) ON DELETE SET NULL,
    FOREIGN KEY(research_project_id)
        REFERENCES research_projects(project_id) ON DELETE SET NULL,
    CHECK(workspace_type IN ('learning', 'teaching', 'research')),
    CHECK(research_project_id IS NULL OR workspace_type = 'research')
)
"""

MESSAGES_DDL = """
CREATE TABLE {table} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    name TEXT,
    attachments_json TEXT NOT NULL DEFAULT '[]',
    is_visible INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(conversation_id)
        REFERENCES conversations(conversation_id) ON DELETE CASCADE
)
"""

PROFILE_AUDIT_DDL = """
CREATE TABLE {table} (
    audit_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    field_key TEXT,
    before_json TEXT,
    after_json TEXT,
    actor TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
)
"""

PROFILE_VERSIONS_DDL = """
CREATE TABLE {table} (
    user_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    generated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, version),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
)
"""

TURN_LEASES_DDL = """
CREATE TABLE {table} (
    conversation_id TEXT PRIMARY KEY,
    owner_token TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY(conversation_id)
        REFERENCES conversations(conversation_id) ON DELETE CASCADE
)
"""


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    """处理 `_table_exists` 相关逻辑。"""
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    """处理 `_columns` 相关逻辑。"""
    return {
        str(row["name"])
        for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


def _migrate_message_attachments(connection: sqlite3.Connection) -> None:
    """Persist attachment metadata without failing on already-upgraded stores."""
    if not _table_exists(connection, "messages"):
        return
    if "attachments_json" not in _columns(connection, "messages"):
        connection.execute(
            "ALTER TABLE messages ADD COLUMN attachments_json "
            "TEXT NOT NULL DEFAULT '[]'"
        )


def _migrate_product_ui_state(connection: sqlite3.Connection) -> None:
    """Persist formerly client-only account and planner state."""
    if _table_exists(connection, "users"):
        user_columns = _columns(connection, "users")
        if "display_name" not in user_columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''"
            )
            # The oldest supported test/production stores only carried the stable
            # user id.  Prefer the login name when it exists, but never make this
            # additive migration depend on a column introduced by a later schema.
            source_column = "username" if "username" in user_columns else "id"
            connection.execute(
                f'UPDATE users SET display_name = "{source_column}" '
                "WHERE display_name = ''"
            )
    if _table_exists(connection, "groups"):
        columns = _columns(connection, "groups")
        if "project_id" not in columns:
            connection.execute("ALTER TABLE groups ADD COLUMN project_id TEXT")
        if "pinned" not in columns:
            connection.execute(
                "ALTER TABLE groups ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
            )
        if "sort_order" not in columns:
            connection.execute(
                "ALTER TABLE groups ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
            )
    if _table_exists(connection, "conversations") and "pinned" not in _columns(
        connection, "conversations"
    ):
        connection.execute(
            "ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
        )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS planner_todos (
            todo_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            due_at TEXT,
            done INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_planner_todos_user "
        "ON planner_todos(user_id, done, due_at, created_at DESC)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS planner_goals (
            goal_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            target_at TEXT,
            progress INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            CHECK(progress BETWEEN 0 AND 100)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_planner_goals_user "
        "ON planner_goals(user_id, target_at, created_at DESC)"
    )


def _execute_script_atomically(
    connection: sqlite3.Connection,
    script: str,
) -> None:
    """Execute a SQL script without sqlite3.executescript's implicit commit."""
    statement = ""
    for line in script.splitlines():
        statement += f"{line}\n"
        if sqlite3.complete_statement(statement):
            sql = statement.strip()
            if sql:
                connection.execute(sql)
            statement = ""
    if statement.strip():
        raise sqlite3.OperationalError("incomplete SQL statement in migration")


def _has_foreign_key(
    connection: sqlite3.Connection,
    table: str,
    source_column: str,
    target_table: str,
    target_column: str,
    on_delete: str,
) -> bool:
    """判断是否存在 `foreign key` 相关数据。"""
    expected_delete = on_delete.upper()
    return any(
        row["from"] == source_column
        and row["table"] == target_table
        and row["to"] == target_column
        and str(row["on_delete"]).upper() == expected_delete
        for row in connection.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
    )


def _ensure_quarantine_table(connection: sqlite3.Connection) -> None:
    """确保 `quarantine table` 相关数据。"""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS migration_orphans (
            quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_table TEXT NOT NULL,
            source_key TEXT NOT NULL,
            row_json TEXT NOT NULL,
            reason TEXT NOT NULL,
            quarantined_at TEXT NOT NULL,
            UNIQUE(source_table, source_key, reason)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_migration_orphans_source
        ON migration_orphans (source_table, source_key)
        """
    )


def _quarantine_rows(
    connection: sqlite3.Connection,
    *,
    source_table: str,
    key_columns: tuple[str, ...],
    reason: str,
    query: str,
) -> int:
    """处理 `_quarantine_rows` 相关逻辑。"""
    rows = connection.execute(query).fetchall()
    if not rows:
        return 0

    _ensure_quarantine_table(connection)
    quarantined_at = datetime.now(timezone.utc).isoformat()
    for row in rows:
        payload = dict(row)
        source_key = "|".join(
            f"{column}={payload.get(column)!s}" for column in key_columns
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO migration_orphans (
                source_table, source_key, row_json, reason, quarantined_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                source_table,
                source_key,
                json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
                reason,
                quarantined_at,
            ),
        )

    logger.warning(
        "数据库迁移隔离了 %d 条孤儿记录: table=%s reason=%s",
        len(rows),
        source_table,
        reason,
    )
    return len(rows)


def _replace_table(
    connection: sqlite3.Connection,
    *,
    table: str,
    ddl: str,
    columns: tuple[str, ...],
    select_sql: str,
) -> None:
    """替换 `table` 相关数据。"""
    replacement = f"__migration_{table}"
    connection.execute(f'DROP TABLE IF EXISTS "{replacement}"')
    connection.execute(ddl.format(table=replacement))
    column_sql = ", ".join(columns)
    connection.execute(f'INSERT INTO "{replacement}" ({column_sql}) {select_sql}')
    connection.execute(f'DROP TABLE "{table}"')
    connection.execute(f'ALTER TABLE "{replacement}" RENAME TO "{table}"')


def _migrate_sessions(connection: sqlite3.Connection) -> None:
    """处理 `_migrate_sessions` 相关逻辑。"""
    if not _table_exists(connection, "sessions"):
        connection.execute(SESSIONS_DDL.format(table="sessions"))
        return
    if _has_foreign_key(connection, "sessions", "user_id", "users", "id", "CASCADE"):
        return

    _quarantine_rows(
        connection,
        source_table="sessions",
        key_columns=("session_id",),
        reason="missing users.id",
        query="""
            SELECT s.* FROM sessions s
            LEFT JOIN users u ON u.id = s.user_id
            WHERE u.id IS NULL
        """,
    )
    _replace_table(
        connection,
        table="sessions",
        ddl=SESSIONS_DDL,
        columns=("session_id", "user_id", "issued_at", "expires_at"),
        select_sql="""
            SELECT s.session_id, s.user_id, s.issued_at, s.expires_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
        """,
    )


def _migrate_groups(connection: sqlite3.Connection) -> None:
    """处理 `_migrate_groups` 相关逻辑。"""
    if not _table_exists(connection, "groups"):
        connection.execute(GROUPS_DDL.format(table="groups"))
    elif not _has_foreign_key(
        connection, "groups", "user_id", "users", "id", "CASCADE"
    ):
        _quarantine_rows(
            connection,
            source_table="groups",
            key_columns=("group_id",),
            reason="missing users.id",
            query="""
                SELECT g.* FROM groups g
                LEFT JOIN users u ON u.id = g.user_id
                WHERE u.id IS NULL
            """,
        )
        _replace_table(
            connection,
            table="groups",
            ddl=GROUPS_DDL,
            columns=(
                "group_id",
                "user_id",
                "name",
                "description",
                "custom_instruction",
                "style",
                "tone",
                "created_at",
                "updated_at",
            ),
            select_sql="""
                SELECT g.group_id, g.user_id, g.name, g.description,
                       g.custom_instruction, g.style, g.tone,
                       g.created_at, g.updated_at
                FROM groups g
                JOIN users u ON u.id = g.user_id
            """,
        )

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_groups_user ON groups (user_id, updated_at)"
    )


def _migrate_conversations(connection: sqlite3.Connection) -> None:
    """处理 `_migrate_conversations` 相关逻辑。"""
    if not _table_exists(connection, "conversations"):
        connection.execute(CONVERSATIONS_DDL.format(table="conversations"))
    else:
        if "group_id" not in _columns(connection, "conversations"):
            connection.execute("ALTER TABLE conversations ADD COLUMN group_id TEXT")

        required_keys = (
            _has_foreign_key(
                connection,
                "conversations",
                "user_id",
                "users",
                "id",
                "CASCADE",
            ),
            _has_foreign_key(
                connection,
                "conversations",
                "group_id",
                "groups",
                "group_id",
                "SET NULL",
            ),
        )
        if not all(required_keys):
            _quarantine_rows(
                connection,
                source_table="conversations",
                key_columns=("conversation_id",),
                reason="missing users.id",
                query="""
                    SELECT c.* FROM conversations c
                    LEFT JOIN users u ON u.id = c.user_id
                    WHERE u.id IS NULL
                """,
            )
            _quarantine_rows(
                connection,
                source_table="conversations",
                key_columns=("conversation_id",),
                reason="missing or cross-user groups.group_id; group_id reset to NULL",
                query="""
                    SELECT c.* FROM conversations c
                    LEFT JOIN groups g ON g.group_id = c.group_id
                    WHERE c.group_id IS NOT NULL
                      AND (g.group_id IS NULL OR g.user_id != c.user_id)
                """,
            )
            _replace_table(
                connection,
                table="conversations",
                ddl=CONVERSATIONS_DDL,
                columns=(
                    "conversation_id",
                    "user_id",
                    "title",
                    "group_id",
                    "created_at",
                    "updated_at",
                ),
                select_sql="""
                    SELECT c.conversation_id, c.user_id, c.title,
                           CASE
                               WHEN c.group_id IS NULL THEN NULL
                               WHEN g.group_id IS NOT NULL
                                AND g.user_id = c.user_id THEN c.group_id
                               ELSE NULL
                           END,
                           c.created_at, c.updated_at
                    FROM conversations c
                    JOIN users u ON u.id = c.user_id
                    LEFT JOIN groups g ON g.group_id = c.group_id
                """,
            )

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_user "
        "ON conversations (user_id, updated_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_group "
        "ON conversations (user_id, group_id, updated_at)"
    )


def _migrate_messages(connection: sqlite3.Connection) -> None:
    """处理 `_migrate_messages` 相关逻辑。"""
    if not _table_exists(connection, "messages"):
        connection.execute(MESSAGES_DDL.format(table="messages"))
    else:
        if "is_visible" not in _columns(connection, "messages"):
            connection.execute(
                "ALTER TABLE messages ADD COLUMN is_visible INTEGER NOT NULL DEFAULT 1"
            )
        if not _has_foreign_key(
            connection,
            "messages",
            "conversation_id",
            "conversations",
            "conversation_id",
            "CASCADE",
        ):
            _quarantine_rows(
                connection,
                source_table="messages",
                key_columns=("id",),
                reason="missing conversations.conversation_id",
                query="""
                    SELECT m.* FROM messages m
                    LEFT JOIN conversations c
                      ON c.conversation_id = m.conversation_id
                    WHERE c.conversation_id IS NULL
                """,
            )
            _replace_table(
                connection,
                table="messages",
                ddl=MESSAGES_DDL,
                columns=(
                    "id",
                    "conversation_id",
                    "role",
                    "content",
                    "name",
                    "is_visible",
                    "created_at",
                ),
                select_sql="""
                    SELECT m.id, m.conversation_id, m.role, m.content,
                           m.name, m.is_visible, m.created_at
                    FROM messages m
                    JOIN conversations c
                      ON c.conversation_id = m.conversation_id
                """,
            )

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_conversation "
        "ON messages (conversation_id, id)"
    )


def _migrate_profile_tables(connection: sqlite3.Connection) -> None:
    """处理 `_migrate_profile_tables` 相关逻辑。"""
    if not _table_exists(connection, "profile_audit_log"):
        connection.execute(PROFILE_AUDIT_DDL.format(table="profile_audit_log"))
    elif not _has_foreign_key(
        connection,
        "profile_audit_log",
        "user_id",
        "users",
        "id",
        "CASCADE",
    ):
        _quarantine_rows(
            connection,
            source_table="profile_audit_log",
            key_columns=("audit_id",),
            reason="missing users.id",
            query="""
                SELECT a.* FROM profile_audit_log a
                LEFT JOIN users u ON u.id = a.user_id
                WHERE u.id IS NULL
            """,
        )
        _replace_table(
            connection,
            table="profile_audit_log",
            ddl=PROFILE_AUDIT_DDL,
            columns=(
                "audit_id",
                "user_id",
                "action",
                "field_key",
                "before_json",
                "after_json",
                "actor",
                "created_at",
            ),
            select_sql="""
                SELECT a.audit_id, a.user_id, a.action, a.field_key,
                       a.before_json, a.after_json, a.actor, a.created_at
                FROM profile_audit_log a
                JOIN users u ON u.id = a.user_id
            """,
        )

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_user_id ON profile_audit_log(user_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_created_at "
        "ON profile_audit_log(created_at)"
    )

    if not _table_exists(connection, "profile_versions"):
        connection.execute(PROFILE_VERSIONS_DDL.format(table="profile_versions"))
    elif not _has_foreign_key(
        connection,
        "profile_versions",
        "user_id",
        "users",
        "id",
        "CASCADE",
    ):
        _quarantine_rows(
            connection,
            source_table="profile_versions",
            key_columns=("user_id", "version"),
            reason="missing users.id",
            query="""
                SELECT v.* FROM profile_versions v
                LEFT JOIN users u ON u.id = v.user_id
                WHERE u.id IS NULL
            """,
        )
        _replace_table(
            connection,
            table="profile_versions",
            ddl=PROFILE_VERSIONS_DDL,
            columns=("user_id", "version", "generated_at"),
            select_sql="""
                SELECT v.user_id, v.version, v.generated_at
                FROM profile_versions v
                JOIN users u ON u.id = v.user_id
            """,
        )


def _create_conversation_owner_triggers(connection: sqlite3.Connection) -> None:
    """创建 `conversation owner triggers` 相关数据。"""
    connection.execute("DROP TRIGGER IF EXISTS conversations_group_owner_insert")
    connection.execute("DROP TRIGGER IF EXISTS conversations_group_owner_update")
    connection.execute(
        """
        CREATE TRIGGER conversations_group_owner_insert
        BEFORE INSERT ON conversations
        FOR EACH ROW
        WHEN NEW.group_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM groups
             WHERE group_id = NEW.group_id AND user_id = NEW.user_id
         )
        BEGIN
            SELECT RAISE(ABORT, 'conversation group must belong to its user');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER conversations_group_owner_update
        BEFORE UPDATE OF group_id, user_id ON conversations
        FOR EACH ROW
        WHEN NEW.group_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM groups
             WHERE group_id = NEW.group_id AND user_id = NEW.user_id
         )
        BEGIN
            SELECT RAISE(ABORT, 'conversation group must belong to its user');
        END
        """
    )


def _migrate_relational_integrity(connection: sqlite3.Connection) -> None:
    """为老库补齐外键，并把无法归属的数据保存在隔离表中。"""
    _ensure_quarantine_table(connection)

    # ChatStore 会在迁移前按当前结构补齐触发器。重建 groups 时旧触发器会
    # 短暂引用已删除的表，SQLite 因此拒绝后续 ALTER TABLE；先移除并在
    # 全部父子表就位后统一重建。
    connection.execute("DROP TRIGGER IF EXISTS conversations_group_owner_insert")
    connection.execute("DROP TRIGGER IF EXISTS conversations_group_owner_update")

    # 租约是临时协调状态。启动迁移时不存在正在处理的请求，可以安全重建；
    # 先删除它也避免旧的租约外键阻碍 conversations 表重建。
    connection.execute("DROP TABLE IF EXISTS conversation_turn_leases")

    _migrate_sessions(connection)
    _migrate_groups(connection)
    _migrate_conversations(connection)
    _migrate_messages(connection)
    _migrate_profile_tables(connection)

    connection.execute(TURN_LEASES_DDL.format(table="conversation_turn_leases"))
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_turn_leases_expires "
        "ON conversation_turn_leases (expires_at)"
    )
    _create_conversation_owner_triggers(connection)

    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        details = ", ".join(
            f"{row['table']}[rowid={row['rowid']}] -> {row['parent']}"
            for row in violations[:10]
        )
        raise sqlite3.IntegrityError(
            f"迁移后仍存在外键违规 ({len(violations)}): {details}"
        )


def _migrate_schedule_tables(connection: sqlite3.Connection) -> None:
    """V8：多课程表——建 schedule_tables、courses 补 table_id 并回填默认课表。"""
    from backend.core.stores.schedule_store import ensure_schedule_tables_schema

    ensure_schedule_tables_schema(connection)


def _migrate_email_identity(connection: sqlite3.Connection) -> None:
    """处理 `_migrate_email_identity` 相关逻辑。"""
    columns = _columns(connection, "users")
    if "email" not in columns:
        connection.execute("ALTER TABLE users ADD COLUMN email TEXT")
    if "email_verified_at" not in columns:
        connection.execute("ALTER TABLE users ADD COLUMN email_verified_at TEXT")
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique
        ON users (email COLLATE NOCASE)
        WHERE email IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS email_verification_codes (
            verification_id TEXT PRIMARY KEY,
            email TEXT NOT NULL COLLATE NOCASE,
            purpose TEXT NOT NULL,
            code_digest TEXT NOT NULL,
            requested_ip TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            CHECK(purpose IN ('register', 'bind'))
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_email_codes_email_created
        ON email_verification_codes(email, purpose, created_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_email_codes_ip_created
        ON email_verification_codes(requested_ip, created_at)
        """
    )


def _migrate_research_capabilities(connection: sqlite3.Connection) -> None:
    """Repair the V9 merge collision and install the complete research domain."""
    # V9 existed independently on two branches. Re-running both halves here is
    # intentional: each operation is idempotent and repairs databases that have
    # already recorded either historical V9 variant.
    _migrate_email_identity(connection)

    user_columns = _columns(connection, "users")
    if "account_role" not in user_columns:
        connection.execute(
            "ALTER TABLE users ADD COLUMN account_role TEXT NOT NULL DEFAULT 'student'"
        )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS research_projects (
            project_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            CHECK(status IN ('active', 'archived'))
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_projects_user "
        "ON research_projects(user_id, status, updated_at)"
    )

    conversation_columns = _columns(connection, "conversations")
    if "workspace_type" not in conversation_columns:
        connection.execute(
            "ALTER TABLE conversations ADD COLUMN workspace_type "
            "TEXT NOT NULL DEFAULT 'learning'"
        )
    if "research_project_id" not in conversation_columns:
        connection.execute(
            "ALTER TABLE conversations ADD COLUMN research_project_id TEXT"
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_workspace "
        "ON conversations(user_id, workspace_type, updated_at)"
    )
    _execute_script_atomically(
        connection,
        """
        CREATE TRIGGER IF NOT EXISTS conversations_workspace_insert
        BEFORE INSERT ON conversations
        FOR EACH ROW
        WHEN NEW.workspace_type NOT IN ('learning', 'teaching', 'research')
          OR (NEW.research_project_id IS NOT NULL AND NEW.workspace_type != 'research')
        BEGIN
            SELECT RAISE(ABORT, 'invalid conversation workspace binding');
        END;

        CREATE TRIGGER IF NOT EXISTS conversations_research_project_insert
        BEFORE INSERT ON conversations
        FOR EACH ROW
        WHEN NEW.research_project_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1 FROM research_projects
             WHERE project_id = NEW.research_project_id
               AND user_id = NEW.user_id
         )
        BEGIN
            SELECT RAISE(ABORT, 'research project must belong to conversation user');
        END;

        CREATE TRIGGER IF NOT EXISTS conversations_workspace_update
        BEFORE UPDATE OF workspace_type, research_project_id, user_id ON conversations
        FOR EACH ROW
        WHEN NEW.workspace_type NOT IN ('learning', 'teaching', 'research')
          OR (NEW.research_project_id IS NOT NULL AND NEW.workspace_type != 'research')
          OR (
              NEW.research_project_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM research_projects
                  WHERE project_id = NEW.research_project_id
                    AND user_id = NEW.user_id
              )
          )
        BEGIN
            SELECT RAISE(ABORT, 'invalid conversation workspace binding');
        END;

        CREATE TABLE IF NOT EXISTS research_frontier_jobs (
            job_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            query TEXT NOT NULL,
            time_window_years INTEGER NOT NULL DEFAULT 5,
            max_results INTEGER NOT NULL DEFAULT 20,
            status TEXT NOT NULL DEFAULT 'queued',
            result_json TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            FOREIGN KEY(project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            CHECK(status IN ('queued', 'running', 'succeeded', 'failed')),
            CHECK(time_window_years BETWEEN 1 AND 20),
            CHECK(max_results BETWEEN 5 AND 40)
        );
        CREATE INDEX IF NOT EXISTS idx_frontier_jobs_project
        ON research_frontier_jobs(user_id, project_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS research_documents (
            document_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            document_type TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            CHECK(document_type IN ('outline', 'literature_review', 'paper', 'notes')),
            CHECK(status IN ('active', 'archived'))
        );
        CREATE INDEX IF NOT EXISTS idx_research_documents_project
        ON research_documents(user_id, project_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS research_document_versions (
            document_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            content TEXT NOT NULL,
            operation TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(document_id, version),
            FOREIGN KEY(document_id) REFERENCES research_documents(document_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS research_writing_jobs (
            job_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            instruction TEXT NOT NULL DEFAULT '',
            source_text TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued',
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            FOREIGN KEY(document_id) REFERENCES research_documents(document_id) ON DELETE CASCADE,
            FOREIGN KEY(project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            CHECK(operation IN ('outline', 'literature_review', 'polish', 'format_check')),
            CHECK(status IN ('queued', 'running', 'succeeded', 'failed'))
        );
        CREATE INDEX IF NOT EXISTS idx_research_writing_jobs_document
        ON research_writing_jobs(user_id, document_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS research_datasets (
            dataset_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            media_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0,
            column_count INTEGER NOT NULL DEFAULT 0,
            profile_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'ready',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            CHECK(status IN ('ready', 'invalid', 'archived'))
        );
        CREATE INDEX IF NOT EXISTS idx_research_datasets_project
        ON research_datasets(user_id, project_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS research_analysis_jobs (
            job_id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            analysis_type TEXT NOT NULL,
            parameters_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'queued',
            result_json TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            FOREIGN KEY(dataset_id) REFERENCES research_datasets(dataset_id) ON DELETE CASCADE,
            FOREIGN KEY(project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            CHECK(analysis_type IN ('descriptive', 'correlation', 'group_compare', 'text_frequency')),
            CHECK(status IN ('queued', 'running', 'succeeded', 'failed'))
        );
        CREATE INDEX IF NOT EXISTS idx_research_analysis_jobs_dataset
        ON research_analysis_jobs(user_id, dataset_id, created_at DESC);
        """,
    )


def _migrate_workspace_runtime_domains(connection: sqlite3.Connection) -> None:
    """Install resource bindings, approvals, and CoreMemory V2 atomically."""
    _execute_script_atomically(
        connection,
        """
        CREATE TABLE IF NOT EXISTS classroom_conversation_bindings (
            conversation_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            class_id TEXT NOT NULL,
            assignment_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_classroom_bindings_user_class
        ON classroom_conversation_bindings(user_id, class_id);

        CREATE TABLE IF NOT EXISTS research_project_profiles (
            project_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            agent_instructions TEXT NOT NULL DEFAULT '',
            format_version INTEGER NOT NULL DEFAULT 1,
            revision INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            CHECK(format_version >= 1),
            CHECK(revision >= 1)
        );
        CREATE INDEX IF NOT EXISTS idx_research_project_profiles_user
        ON research_project_profiles(user_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS agent_action_requests (
            action_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            workspace_type TEXT NOT NULL,
            action_type TEXT NOT NULL,
            arguments_json TEXT NOT NULL,
            resource_snapshot_json TEXT NOT NULL DEFAULT '{}',
            policy_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            result_json TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            decided_at TEXT,
            executed_at TEXT,
            completed_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
            UNIQUE(user_id, idempotency_key),
            CHECK(workspace_type IN ('learning', 'teaching', 'research')),
            CHECK(status IN ('pending','approved','executing','succeeded','failed','rejected','expired'))
        );
        CREATE INDEX IF NOT EXISTS idx_agent_actions_user_status
        ON agent_action_requests(user_id, status, created_at DESC);

        CREATE TABLE IF NOT EXISTS core_memories (
            memory_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            memory_key TEXT NOT NULL,
            content TEXT NOT NULL,
            normalized_content_hash TEXT NOT NULL,
            category TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            workspace_type TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            source_type TEXT NOT NULL,
            source_conversation_id TEXT,
            revision INTEGER NOT NULL DEFAULT 1,
            confirmed_at TEXT,
            review_after TEXT,
            expires_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(source_conversation_id) REFERENCES conversations(conversation_id) ON DELETE SET NULL,
            UNIQUE(user_id, scope_type, workspace_type, memory_key),
            CHECK(scope_type IN ('global','workspace')),
            CHECK((scope_type='global' AND workspace_type IS NULL) OR
                  (scope_type='workspace' AND workspace_type IN ('learning','teaching','research'))),
            CHECK(status IN ('active','suppressed')),
            CHECK(revision >= 1)
        );
        CREATE INDEX IF NOT EXISTS idx_core_memories_visible
        ON core_memories(user_id, scope_type, workspace_type, status, updated_at DESC);

        CREATE TABLE IF NOT EXISTS core_memory_candidates (
            candidate_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            memory_id TEXT,
            memory_key TEXT NOT NULL,
            proposed_content TEXT,
            normalized_content_hash TEXT NOT NULL,
            category TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            workspace_type TEXT,
            candidate_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            expected_revision INTEGER,
            source_conversation_id TEXT,
            resulting_memory_id TEXT,
            created_at TEXT NOT NULL,
            decided_at TEXT,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(memory_id) REFERENCES core_memories(memory_id) ON DELETE CASCADE,
            FOREIGN KEY(resulting_memory_id) REFERENCES core_memories(memory_id) ON DELETE SET NULL,
            FOREIGN KEY(source_conversation_id) REFERENCES conversations(conversation_id) ON DELETE SET NULL,
            CHECK(scope_type IN ('global','workspace')),
            CHECK((scope_type='global' AND workspace_type IS NULL) OR
                  (scope_type='workspace' AND workspace_type IN ('learning','teaching','research'))),
            CHECK(candidate_type IN ('create','update','replace')),
            CHECK(status IN ('pending','accepted','rejected','expired'))
        );
        CREATE INDEX IF NOT EXISTS idx_memory_candidates_user_status
        ON core_memory_candidates(user_id, status, created_at DESC);

        CREATE TABLE IF NOT EXISTS core_memory_versions (
            version_id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            content TEXT NOT NULL,
            category TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            workspace_type TEXT,
            change_type TEXT NOT NULL,
            changed_via TEXT NOT NULL,
            source_candidate_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(memory_id) REFERENCES core_memories(memory_id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(memory_id, revision),
            CHECK(change_type IN ('create','update','replace','restore','migration'))
        );
        CREATE TABLE IF NOT EXISTS core_memory_tombstones (
            memory_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            deleted_at TEXT NOT NULL,
            final_revision INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS core_memory_audit_log (
            event_id TEXT PRIMARY KEY,
            memory_id TEXT,
            user_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            scope_type TEXT,
            workspace_type TEXT,
            revision INTEGER,
            content_hash TEXT,
            request_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_memory_audit_user_created
        ON core_memory_audit_log(user_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS core_memory_user_revisions (
            user_id TEXT PRIMARY KEY,
            revision INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """,
    )


MIGRATIONS: list[MigrationDef] = [
    (
        1,
        "create_user_profile_dimensions",
        [
            """
            CREATE TABLE IF NOT EXISTS user_profile_dimensions (
                user_id TEXT NOT NULL,
                field_key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                origin TEXT NOT NULL,
                confidence REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                source_memory_ids_json TEXT NOT NULL DEFAULT '[]',
                last_confirmed_at TEXT,
                expires_at TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, field_key),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """,
        ],
    ),
    (
        2,
        "create_memory_settings",
        [
            """
            CREATE TABLE IF NOT EXISTS memory_settings (
                user_id TEXT PRIMARY KEY,
                saved_memory_enabled INTEGER NOT NULL DEFAULT 1,
                chat_history_enabled INTEGER NOT NULL DEFAULT 1,
                auto_extract_enabled INTEGER NOT NULL DEFAULT 0,
                learning_profile_enabled INTEGER NOT NULL DEFAULT 1,
                inferred_profile_enabled INTEGER NOT NULL DEFAULT 1,
                default_conversation_mode TEXT NOT NULL DEFAULT 'normal',
                episodic_retention_days INTEGER NOT NULL DEFAULT 180,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                CHECK(default_conversation_mode IN ('normal', 'no_write', 'isolated'))
            )
            """,
        ],
    ),
    (
        3,
        "create_profile_audit_log",
        [
            """
            CREATE TABLE IF NOT EXISTS profile_audit_log (
                audit_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                action TEXT NOT NULL,
                field_key TEXT,
                before_json TEXT,
                after_json TEXT,
                actor TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_audit_user_id ON profile_audit_log(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_created_at ON profile_audit_log(created_at)",
        ],
    ),
    (
        4,
        "create_profile_versions",
        [
            """
            CREATE TABLE IF NOT EXISTS profile_versions (
                user_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                generated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, version),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """,
        ],
    ),
    (
        5,
        "enforce_relational_integrity_and_add_turn_leases",
        _migrate_relational_integrity,
    ),
    (
        6,
        "create_user_courses",
        [
            """
            CREATE TABLE IF NOT EXISTS user_courses (
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                canonical_course TEXT,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, name),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                CHECK(source IN ('manual', 'timetable'))
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_user_courses_user_id ON user_courses(user_id)",
        ],
    ),
    (
        7,
        "create_user_schedules",
        [
            """
            CREATE TABLE IF NOT EXISTS schedule_courses (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                teacher TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                weekday INTEGER NOT NULL,
                start_period INTEGER NOT NULL,
                end_period INTEGER NOT NULL,
                start_week INTEGER NOT NULL,
                end_week INTEGER NOT NULL,
                color_value INTEGER NOT NULL DEFAULT 4280701931,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                CHECK(weekday BETWEEN 1 AND 7),
                CHECK(start_period BETWEEN 1 AND 24),
                CHECK(end_period BETWEEN start_period AND 24),
                CHECK(start_week BETWEEN 1 AND 30),
                CHECK(end_week BETWEEN start_week AND 30)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_schedule_courses_user ON schedule_courses(user_id, weekday, start_period)",
            """
            CREATE TABLE IF NOT EXISTS schedule_settings (
                user_id TEXT PRIMARY KEY,
                morning_period_count INTEGER NOT NULL DEFAULT 4,
                afternoon_period_count INTEGER NOT NULL DEFAULT 4,
                evening_period_count INTEGER NOT NULL DEFAULT 4,
                morning_start_minutes INTEGER NOT NULL DEFAULT 480,
                afternoon_start_minutes INTEGER NOT NULL DEFAULT 840,
                evening_start_minutes INTEGER NOT NULL DEFAULT 1140,
                period_duration_minutes INTEGER NOT NULL DEFAULT 45,
                break_duration_minutes INTEGER NOT NULL DEFAULT 10,
                term_start_date TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """,
        ],
    ),
    (
        8,
        "create_presence_and_conversation_summaries",
        [
            """
            CREATE TABLE IF NOT EXISTS user_presence (
                user_id TEXT PRIMARY KEY,
                is_online INTEGER NOT NULL DEFAULT 0,
                last_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS conversation_summaries (
                conversation_id TEXT PRIMARY KEY,
                summarized_through_message_id INTEGER NOT NULL DEFAULT 0,
                summary TEXT NOT NULL,
                source_message_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id)
                    REFERENCES conversations(conversation_id) ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_conversation_summaries_updated
            ON conversation_summaries(updated_at)
            """,
        ],
    ),
    (
    9,
        "create_email_identity_and_verification_codes",
        _migrate_email_identity,
    ),
    (
        10,
        "repair_v9_and_create_research_capabilities",
        _migrate_research_capabilities,
    ),
    (
        11,
        "create_workspace_runtime_domains",
        _migrate_workspace_runtime_domains,
    ),
    (
        12,
        "persist_message_attachments",
        _migrate_message_attachments,
    ),
    (
        13,
        "persist_product_ui_state_and_planner",
        _migrate_product_ui_state,
    ),
]


def run_migrations(database_path: str | Path) -> int:
    """按版本执行未应用迁移，每个版本失败时完整回滚。"""
    db_path = Path(database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    applied = 0
    connection = connect_sqlite(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL,
                description TEXT
            )
            """
        )
        connection.commit()

        applied_versions = {
            int(row["version"])
            for row in connection.execute(
                "SELECT version FROM schema_migrations"
            ).fetchall()
        }

        for version, description, action in MIGRATIONS:
            if version in applied_versions:
                continue

            logger.info("应用数据库迁移 V%03d: %s", version, description)
            try:
                # SQLite 官方推荐在重建表时临时关闭约束，完成后使用
                # foreign_key_check 验证，再恢复每连接外键开关。
                connection.commit()
                connection.execute("PRAGMA foreign_keys = OFF")
                connection.execute("BEGIN IMMEDIATE")

                if callable(action):
                    action(connection)
                else:
                    for statement in action:
                        connection.execute(statement)

                connection.execute(
                    """
                    INSERT INTO schema_migrations (
                        version, applied_at, description
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        version,
                        datetime.now(timezone.utc).isoformat(),
                        description,
                    ),
                )
                connection.commit()
                applied += 1
            except Exception:
                connection.rollback()
                logger.exception("数据库迁移 V%03d 失败，已回滚", version)
                raise
            finally:
                connection.execute("PRAGMA foreign_keys = ON")

        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise sqlite3.IntegrityError(f"数据库仍存在 {len(violations)} 条外键违规")
    finally:
        connection.close()

    if applied:
        logger.info("数据库迁移完成，新应用 %d 个", applied)
    return applied
