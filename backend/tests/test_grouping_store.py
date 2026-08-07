import sqlite3

from backend.core.stores.chat_store import ChatStore
from backend.core.stores.group_store import GroupStore


def test_legacy_database_migrates_and_supports_grouping(tmp_path):
    db_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE conversations (
            conversation_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()

    chat_store = ChatStore(db_path)
    group_store = GroupStore(db_path)

    columns = {
        row[1]
        for row in sqlite3.connect(db_path).execute(
            "PRAGMA table_info(conversations)"
        )
    }
    assert "group_id" in columns

    group = group_store.create_group(
        user_id="u1",
        name="算法",
        custom_instruction="优先使用伪代码",
        style="detailed",
        group_limit=20,
    )
    assert group is not None

    conversation = chat_store.create_conversation(
        user_id="u1",
        title="排序算法",
        group_id=group["group_id"],
    )
    assert conversation["group_id"] == group["group_id"]
    assert chat_store.get_conversation(conversation["conversation_id"])[
        "group_id"
    ] == group["group_id"]
    assert group_store.get_group(group["group_id"])["conversation_count"] == 1


def test_move_delete_and_ownership_guards(tmp_path):
    db_path = tmp_path / "esa.db"
    chat_store = ChatStore(db_path)
    group_store = GroupStore(db_path)

    group_u1 = group_store.create_group("u1", "数学")
    group_u2 = group_store.create_group("u2", "私有分组")
    assert group_u1 is not None and group_u2 is not None

    conversation = chat_store.create_conversation("u1", "线代")
    conversation_id = conversation["conversation_id"]

    assert not chat_store.set_conversation_group(
        conversation_id,
        group_u1["group_id"],
        user_id="u2",
    )
    assert chat_store.set_conversation_group(
        conversation_id,
        group_u1["group_id"],
        user_id="u1",
    )
    assert group_store.get_group(group_u1["group_id"], "u1")[
        "conversation_count"
    ] == 1
    assert group_store.get_group(group_u2["group_id"], "u1") is None

    assert not group_store.delete_group(group_u1["group_id"], "u2")
    assert group_store.delete_group(group_u1["group_id"], "u1")
    assert chat_store.get_conversation(conversation_id)["group_id"] is None


def test_group_limit_is_enforced(tmp_path):
    db_path = tmp_path / "esa.db"
    ChatStore(db_path)
    group_store = GroupStore(db_path)

    assert group_store.create_group("u1", "A", group_limit=1) is not None
    assert group_store.create_group("u1", "B", group_limit=1) is None
    assert group_store.create_group("u2", "C", group_limit=1) is not None


def test_list_conversations_can_filter_group_and_ungrouped(tmp_path):
    db_path = tmp_path / "esa.db"
    chat_store = ChatStore(db_path)
    group_store = GroupStore(db_path)
    group = group_store.create_group("u1", "系统")
    assert group is not None

    chat_store.create_conversation("u1", "已分组", group["group_id"])
    chat_store.create_conversation("u1", "未分组")

    assert len(chat_store.list_conversations("u1")) == 2
    assert len(chat_store.list_conversations("u1", group["group_id"])) == 1
    ungrouped = chat_store.list_conversations(
        "u1",
        group_id=None,
        include_all_groups=False,
    )
    assert [item["title"] for item in ungrouped] == ["未分组"]


def test_update_conversation_is_atomic_and_user_scoped(tmp_path):
    db_path = tmp_path / "esa.db"
    chat_store = ChatStore(db_path)
    group_store = GroupStore(db_path)

    group = group_store.create_group("u1", "算法")
    assert group is not None
    conversation = chat_store.create_conversation("u1", "旧标题")
    conversation_id = conversation["conversation_id"]

    assert not chat_store.update_conversation(
        conversation_id,
        "u2",
        title="越权标题",
        group_id=group["group_id"],
    )
    unchanged = chat_store.get_conversation(conversation_id, user_id="u1")
    assert unchanged is not None
    assert unchanged["title"] == "旧标题"
    assert unchanged["group_id"] is None

    assert chat_store.update_conversation(
        conversation_id,
        "u1",
        title="新标题",
        group_id=group["group_id"],
    )
    updated = chat_store.get_conversation(conversation_id, user_id="u1")
    assert updated is not None
    assert updated["title"] == "新标题"
    assert updated["group_id"] == group["group_id"]


def test_update_conversation_can_move_to_ungrouped(tmp_path):
    db_path = tmp_path / "esa.db"
    chat_store = ChatStore(db_path)
    group_store = GroupStore(db_path)

    group = group_store.create_group("u1", "数学")
    assert group is not None
    conversation = chat_store.create_conversation(
        "u1",
        "线性代数",
        group["group_id"],
    )

    assert chat_store.update_conversation(
        conversation["conversation_id"],
        "u1",
        group_id=None,
    )
    updated = chat_store.get_conversation(
        conversation["conversation_id"],
        user_id="u1",
    )
    assert updated is not None
    assert updated["group_id"] is None
