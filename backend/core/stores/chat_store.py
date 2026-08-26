# backend/core/stores/chat_store.py

"""提供数据持久化实现。"""

from __future__ import annotations

import json
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


_UNSET = object()
_SHANGHAI_TIMEZONE = timezone(timedelta(hours=8))


class ChatStore(BaseSQLiteStore):
    """聊天记录读写类。"""

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        """初始化 `ChatStore` 实例。"""
        super().__init__(database_path)

    def _initialize(self) -> None:
        """初始化 conversations、messages 表并迁移旧数据库。"""
        with closing(self._connect()) as connection, connection:
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
                """
                CREATE TABLE IF NOT EXISTS conversations (
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
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model_content TEXT,
                    name TEXT,
                    tool_call_id TEXT,
                    attachments_json TEXT NOT NULL DEFAULT '[]',
                    is_visible INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id)
                        REFERENCES conversations(conversation_id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_audit_log (
                    tool_call_id TEXT PRIMARY KEY,
                    message_id INTEGER NOT NULL UNIQUE,
                    conversation_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    request_id TEXT,
                    run_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE,
                    FOREIGN KEY(conversation_id)
                        REFERENCES conversations(conversation_id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_turn_leases (
                    conversation_id TEXT PRIMARY KEY,
                    owner_token TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id)
                        REFERENCES conversations(conversation_id) ON DELETE CASCADE
                )
                """
            )

            conversation_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(conversations)"
                ).fetchall()
            }
            if "group_id" not in conversation_columns:
                connection.execute("ALTER TABLE conversations ADD COLUMN group_id TEXT")
            if "workspace_type" not in conversation_columns:
                connection.execute(
                    "ALTER TABLE conversations ADD COLUMN workspace_type TEXT NOT NULL DEFAULT 'learning'"
                )
            if "research_project_id" not in conversation_columns:
                connection.execute(
                    "ALTER TABLE conversations ADD COLUMN research_project_id TEXT"
                )
            if "pinned" not in conversation_columns:
                connection.execute(
                    "ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
                )

            message_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "is_visible" not in message_columns:
                connection.execute(
                    """
                    ALTER TABLE messages
                    ADD COLUMN is_visible INTEGER NOT NULL DEFAULT 1
                    """
                )
            if "attachments_json" not in message_columns:
                connection.execute(
                    "ALTER TABLE messages ADD COLUMN attachments_json "
                    "TEXT NOT NULL DEFAULT '[]'"
                )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                ON messages (conversation_id, id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversations_user
                ON conversations (user_id, updated_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversations_group
                ON conversations (user_id, group_id, updated_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversations_workspace
                ON conversations (user_id, workspace_type, updated_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_turn_leases_expires
                ON conversation_turn_leases (expires_at)
                """
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS conversations_group_owner_insert
                BEFORE INSERT ON conversations
                FOR EACH ROW
                WHEN NEW.group_id IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM groups
                     WHERE group_id = NEW.group_id
                       AND user_id = NEW.user_id
                 )
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'conversation group must belong to its user'
                    );
                END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS conversations_group_owner_update
                BEFORE UPDATE OF group_id, user_id ON conversations
                FOR EACH ROW
                WHEN NEW.group_id IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM groups
                     WHERE group_id = NEW.group_id
                       AND user_id = NEW.user_id
                 )
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'conversation group must belong to its user'
                    );
                END
                """
            )

    @staticmethod
    def _now() -> str:
        """处理 `_now` 相关逻辑。"""
        return datetime.now(timezone.utc).isoformat()

    def create_conversation(
        self,
        user_id: str,
        title: str = "新对话",
        group_id: str | None = None,
        *,
        workspace_type: str = "learning",
        research_project_id: str | None = None,
    ) -> dict:
        """创建 `conversation` 相关数据。

        Args:
            user_id: str => 用户 ID。
            title: str => `title` 参数。
            group_id: str | None => 分组 ID。
            workspace_type: str => `workspace_type` 参数。
            research_project_id: str | None => research project ID。

        Returns:
            dict => 处理结果。
        """
        now = self._now()
        conversation: dict = {
            "conversation_id": str(uuid.uuid4()),
            "user_id": user_id,
            "title": title,
            "group_id": group_id,
            "workspace_type": workspace_type,
            "research_project_id": research_project_id,
            "pinned": False,
            "created_at": now,
            "updated_at": now,
        }
        self.execute(
            """
            INSERT INTO conversations (
                conversation_id,
                user_id,
                title,
                group_id,
                workspace_type,
                research_project_id,
                pinned,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation["conversation_id"],
                conversation["user_id"],
                conversation["title"],
                conversation["group_id"],
                conversation["workspace_type"],
                conversation["research_project_id"],
                0,
                conversation["created_at"],
                conversation["updated_at"],
            ),
        )
        return conversation

    def get_conversation(
        self,
        conversation_id: str,
        user_id: str | None = None,
    ) -> dict | None:
        """获取 `conversation` 相关数据。

        Args:
            conversation_id: str => 对话 ID。
            user_id: str | None => 用户 ID。

        Returns:
            dict | None => 处理结果。
        """
        sql = """
            SELECT conversation_id, user_id, title, group_id,
                   workspace_type, research_project_id, pinned,
                   created_at, updated_at
            FROM conversations
            WHERE conversation_id = ?
        """
        params: tuple = (conversation_id,)
        if user_id is not None:
            sql += " AND user_id = ?"
            params += (user_id,)

        row = self.query_one(sql, params)
        if row is None:
            return None
        conversation = dict(row)
        conversation["pinned"] = bool(conversation["pinned"])
        return conversation

    def list_conversations(
        self,
        user_id: str,
        group_id: str | None = None,
        *,
        include_all_groups: bool = True,
        workspace_type: str | None = None,
    ) -> list[dict]:
        """列出用户对话。

        默认返回全部对话。传入 group_id 时仅返回该分组；若要查询未分组，
        传 group_id=None 且 include_all_groups=False。
        """
        sql = """
            SELECT conversation_id, user_id, title, group_id,
                   workspace_type, research_project_id, pinned,
                   created_at, updated_at
            FROM conversations
            WHERE user_id = ?
        """
        params: tuple = (user_id,)
        if not include_all_groups:
            if group_id is None:
                sql += " AND group_id IS NULL"
            else:
                sql += " AND group_id = ?"
                params += (group_id,)
        elif group_id is not None:
            sql += " AND group_id = ?"
            params += (group_id,)
        if workspace_type is not None:
            sql += " AND workspace_type = ?"
            params += (workspace_type,)

        sql += " ORDER BY pinned DESC, updated_at DESC"
        conversations = [dict(row) for row in self.query_all(sql, params)]
        for conversation in conversations:
            conversation["pinned"] = bool(conversation["pinned"])
        return conversations

    def rename_conversation(
        self,
        conversation_id: str,
        title: str,
        user_id: str | None = None,
    ) -> bool:
        """处理 `rename_conversation` 相关逻辑。

        Args:
            conversation_id: str => 对话 ID。
            title: str => `title` 参数。
            user_id: str | None => 用户 ID。

        Returns:
            bool => 处理结果。
        """
        sql = """
            UPDATE conversations
            SET title = ?, updated_at = ?
            WHERE conversation_id = ?
        """
        params: tuple = (title, self._now(), conversation_id)
        if user_id is not None:
            sql += " AND user_id = ?"
            params += (user_id,)
        return self.execute(sql, params) > 0

    def rename_conversation_if_title(
        self,
        conversation_id: str,
        *,
        expected_title: str,
        title: str,
        user_id: str | None = None,
    ) -> bool:
        """Rename only if nobody changed the current title in the meantime."""

        sql = """
            UPDATE conversations
            SET title = ?, updated_at = ?
            WHERE conversation_id = ? AND title = ?
        """
        params: tuple = (
            title,
            self._now(),
            conversation_id,
            expected_title,
        )
        if user_id is not None:
            sql += " AND user_id = ?"
            params += (user_id,)
        return self.execute(sql, params) > 0

    def set_conversation_group(
        self,
        conversation_id: str,
        group_id: str | None,
        user_id: str | None = None,
    ) -> bool:
        """移动对话；移动本身不改变最近聊天时间。"""
        sql = """
            UPDATE conversations
            SET group_id = ?
            WHERE conversation_id = ?
        """
        params: tuple = (group_id, conversation_id)
        if user_id is not None:
            sql += " AND user_id = ?"
            params += (user_id,)
        return self.execute(sql, params) > 0

    def update_conversation(
        self,
        conversation_id: str,
        user_id: str,
        *,
        title: str | object = _UNSET,
        group_id: str | None | object = _UNSET,
        pinned: bool | object = _UNSET,
    ) -> bool:
        """在同一事务中修改对话标题和分组。

        只有修改标题时才刷新 ``updated_at``；单纯移动分组不会改变
        对话最近活动时间。
        """
        assignments: list[str] = []
        params: list[object] = []

        if title is not _UNSET:
            if not isinstance(title, str):
                raise ValueError("title 必须是字符串")
            assignments.extend(["title = ?", "updated_at = ?"])
            params.extend([title, self._now()])

        if group_id is not _UNSET:
            if group_id is not None and not isinstance(group_id, str):
                raise ValueError("group_id 必须是字符串或 None")
            assignments.append("group_id = ?")
            params.append(group_id)

        if pinned is not _UNSET:
            if not isinstance(pinned, bool):
                raise ValueError("pinned 必须是布尔值")
            assignments.append("pinned = ?")
            params.append(int(pinned))

        if not assignments:
            return (
                self.get_conversation(
                    conversation_id,
                    user_id=user_id,
                )
                is not None
            )

        params.extend([conversation_id, user_id])
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                f"""
                UPDATE conversations
                SET {", ".join(assignments)}
                WHERE conversation_id = ?
                  AND user_id = ?
                """,
                tuple(params),
            )
            return cursor.rowcount > 0

    def delete_conversation(
        self,
        conversation_id: str,
        user_id: str | None = None,
    ) -> bool:
        """删除 `conversation` 相关数据。

        Args:
            conversation_id: str => 对话 ID。
            user_id: str | None => 用户 ID。

        Returns:
            bool => 处理结果。
        """
        with closing(self._connect()) as connection, connection:
            where = "conversation_id = ?"
            params: tuple = (conversation_id,)
            if user_id is not None:
                where += " AND user_id = ?"
                params += (user_id,)

            row = connection.execute(
                f"SELECT conversation_id FROM conversations WHERE {where}",
                params,
            ).fetchone()
            if row is None:
                return False

            connection.execute(
                "DELETE FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            cursor = connection.execute(
                f"DELETE FROM conversations WHERE {where}",
                params,
            )
            return cursor.rowcount > 0

    def get_user_stats(
        self,
        user_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, int]:
        """Return account-wide conversation, pin, and learning-streak stats."""
        counts = self.query_one(
            """
            SELECT COUNT(*) AS conversation_count,
                   COALESCE(SUM(pinned), 0) AS pinned_count
            FROM conversations
            WHERE user_id = ?
            """,
            (user_id,),
        )
        active_rows = self.query_all(
            """
            SELECT DISTINCT date(m.created_at, '+8 hours') AS active_date
            FROM messages m
            JOIN conversations c ON c.conversation_id = m.conversation_id
            WHERE c.user_id = ? AND m.role = 'user'
            ORDER BY active_date DESC
            """,
            (user_id,),
        )
        active_dates = {
            datetime.fromisoformat(str(row["active_date"])).date()
            for row in active_rows
            if row["active_date"]
        }
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        today = current.astimezone(_SHANGHAI_TIMEZONE).date()
        cursor = today
        if cursor not in active_dates:
            cursor = today - timedelta(days=1)
        streak = 0
        while cursor in active_dates:
            streak += 1
            cursor -= timedelta(days=1)
        return {
            "conversation_count": int(counts["conversation_count"] if counts else 0),
            "pinned_count": int(counts["pinned_count"] if counts else 0),
            "learning_streak_days": streak,
        }

    def append_messages(
        self,
        conversation_id: str,
        messages: list[dict],
    ) -> None:
        """追加 `messages` 相关数据。

        Args:
            conversation_id: str => 对话 ID。
            messages: list[dict] => 消息列表。
        """
        if not messages:
            return

        current_time = self._now()
        with closing(self._connect()) as connection, connection:
            exists = connection.execute(
                "SELECT 1 FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if exists is None:
                raise ValueError("对话不存在")

            self._insert_messages(connection, conversation_id, messages, current_time)
            connection.execute(
                """
                UPDATE conversations
                SET updated_at = ?
                WHERE conversation_id = ?
                """,
                (current_time, conversation_id),
            )

    @staticmethod
    def _insert_messages(connection, conversation_id: str, messages: list[dict], current_time: str) -> None:
        """Persist display/model projections and audit metadata atomically."""

        for message in messages:
            cursor = connection.execute(
                """
                INSERT INTO messages (
                    conversation_id, role, content, model_content, name,
                    tool_call_id, attachments_json, is_visible, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    message["role"],
                    message["content"],
                    message.get("model_content"),
                    message.get("name"),
                    message.get("tool_call_id"),
                    json.dumps(message.get("attachments", []), ensure_ascii=False),
                    1 if message.get("is_visible", True) else 0,
                    current_time,
                ),
            )
            audit = message.get("audit_metadata")
            tool_call_id = message.get("tool_call_id")
            if audit is None or not isinstance(tool_call_id, str) or not tool_call_id:
                continue
            connection.execute(
                """
                INSERT INTO tool_audit_log (
                    tool_call_id, message_id, conversation_id, tool_name,
                    request_id, run_id, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_call_id,
                    int(cursor.lastrowid),
                    conversation_id,
                    str(message.get("name") or ""),
                    message.get("request_id"),
                    message.get("run_id"),
                    json.dumps(audit, ensure_ascii=False, default=str),
                    current_time,
                ),
            )

    def get_tool_audit(self, tool_call_id: str) -> dict | None:
        """Read one server-side tool audit record for diagnostics."""

        row = self.query_one(
            "SELECT metadata_json FROM tool_audit_log WHERE tool_call_id = ?",
            (tool_call_id,),
        )
        return json.loads(row["metadata_json"]) if row is not None else None

    def get_history(self, conversation_id: str) -> list[dict]:
        """获取 `history` 相关数据。

        Args:
            conversation_id: str => 对话 ID。

        Returns:
            list[dict] => 处理结果。
        """
        rows = self.query_all(
            """
            SELECT id, role, content, name, attachments_json, created_at
            FROM messages
            WHERE conversation_id = ?
              AND is_visible = 1
            ORDER BY id ASC
            """,
            (conversation_id,),
        )
        history = []
        for row in rows:
            message = dict(row)
            try:
                message["attachments"] = json.loads(
                    message.pop("attachments_json") or "[]"
                )
            except (TypeError, json.JSONDecodeError):
                message["attachments"] = []
            history.append(message)
        return history

    def get_latest_attachment_ids(
        self,
        conversation_id: str,
        *,
        limit: int = 3,
    ) -> tuple[str, ...]:
        """Return attachment ids from the latest user message that has files."""
        if limit < 1:
            return ()
        rows = self.query_all(
            """
            SELECT attachments_json
            FROM messages
            WHERE conversation_id = ?
              AND role = 'user'
              AND attachments_json != '[]'
            ORDER BY id DESC
            """,
            (conversation_id,),
        )
        for row in rows:
            try:
                attachments = json.loads(row["attachments_json"] or "[]")
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(attachments, list):
                continue
            attachment_ids: list[str] = []
            for attachment in attachments:
                if isinstance(attachment, dict):
                    value = attachment.get("id") or attachment.get("attachment_id")
                else:
                    value = attachment
                if not isinstance(value, str) or not value or value in attachment_ids:
                    continue
                attachment_ids.append(value)
                if len(attachment_ids) >= limit:
                    break
            if attachment_ids:
                return tuple(attachment_ids)
        return ()

    def latest_message_id(self, conversation_id: str) -> int | None:
        """处理 `latest_message_id` 相关逻辑。"""
        row = self.query_one(
            "SELECT MAX(id) AS id FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        return int(row["id"]) if row is not None and row["id"] is not None else None

    def revise_user_message(
        self,
        conversation_id: str,
        message_id: int,
        content: str,
        attachments: list[dict],
    ) -> tuple[str | None, list[dict]]:
        """Replace one user turn and remove every later turn atomically."""
        current_time = self._now()
        with closing(self._connect()) as connection:
            connection.isolation_level = None
            try:
                connection.execute("BEGIN IMMEDIATE")
                target = connection.execute(
                    """
                    SELECT id, role FROM messages
                    WHERE conversation_id = ? AND id = ?
                    """,
                    (conversation_id, message_id),
                ).fetchone()
                if target is None or target["role"] != "user":
                    raise ValueError("只能修改当前对话中的用户消息")
                rows = connection.execute(
                    """
                    SELECT role, COALESCE(model_content, content) AS content, name
                    WHERE conversation_id = ? AND id < ?
                    ORDER BY id ASC
                    """,
                    (conversation_id, message_id),
                ).fetchall()
                history = []
                for row in rows:
                    message = {"role": row["role"], "content": row["content"]}
                    if row["name"] is not None:
                        message["name"] = row["name"]
                    history.append(message)
                connection.execute(
                    "DELETE FROM messages WHERE conversation_id = ? AND id > ?",
                    (conversation_id, message_id),
                )
                connection.execute(
                    """
                    UPDATE messages
                    SET content = ?, attachments_json = ?, created_at = ?
                    WHERE conversation_id = ? AND id = ?
                    """,
                    (
                        content,
                        json.dumps(attachments, ensure_ascii=False),
                        current_time,
                        conversation_id,
                        message_id,
                    ),
                )
                connection.execute(
                    "DELETE FROM conversation_summaries WHERE conversation_id = ?",
                    (conversation_id,),
                )
                connection.execute(
                    "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                    (current_time, conversation_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return None, history

    def get_model_messages(self, conversation_id: str) -> list[dict]:
        """获取 `model messages` 相关数据。

        Args:
            conversation_id: str => 对话 ID。

        Returns:
            list[dict] => 处理结果。
        """
        rows = self.query_all(
            """
            SELECT role, COALESCE(model_content, content) AS content, name
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        )

        model_messages: list[dict] = []
        for row in rows:
            message: dict = {
                "role": row["role"],
                "content": row["content"],
            }
            if row["name"] is not None:
                message["name"] = row["name"]
            model_messages.append(message)
        return model_messages

    def get_model_history_and_append(
        self,
        conversation_id: str,
        messages: list[dict],
    ) -> list[dict]:
        """原子地读取模型历史并追加消息 返回追加前的历史。

        在同一事务内完成 SELECT + INSERT 并持有写锁 (BEGIN IMMEDIATE)
        避免并发请求下"读到的历史互相缺失对方刚追加的消息" (读-写竞态)。

        Args:
            conversation_id: str    => 对话 id
            messages: list[dict]    => 待追加的消息 每条含 role/content 可选 name/is_visible

        Returns:
            list[dict]              => 追加前的完整模型历史 (与 get_model_messages 同格式)
        """
        _, history = self._get_model_context_and_append(
            conversation_id,
            messages,
            use_summary=False,
        )
        return history

    def get_compressed_model_history_and_append(
        self,
        conversation_id: str,
        messages: list[dict],
    ) -> tuple[str | None, list[dict]]:
        """Return the persisted summary plus raw messages after its boundary."""
        return self._get_model_context_and_append(
            conversation_id,
            messages,
            use_summary=True,
        )

    def get_compressed_model_history_before(
        self,
        conversation_id: str,
        before_message_id: int,
    ) -> tuple[str | None, list[dict]]:
        """Reload summarized history without re-appending the current user turn."""
        summary_row = self.query_one(
            """
            SELECT summary, summarized_through_message_id
            FROM conversation_summaries
            WHERE conversation_id = ?
            """,
            (conversation_id,),
        )
        summary = str(summary_row["summary"]) if summary_row is not None else None
        boundary = (
            int(summary_row["summarized_through_message_id"])
            if summary_row is not None
            else 0
        )
        rows = self.query_all(
            """
            SELECT role, COALESCE(model_content, content) AS content, name
            FROM messages
            WHERE conversation_id = ? AND id > ? AND id < ?
            ORDER BY id ASC
            """,
            (conversation_id, boundary, before_message_id),
        )
        history: list[dict] = []
        for row in rows:
            message = {"role": row["role"], "content": row["content"]}
            if row["name"] is not None:
                message["name"] = row["name"]
            history.append(message)
        return summary, history

    def _get_model_context_and_append(
        self,
        conversation_id: str,
        messages: list[dict],
        *,
        use_summary: bool,
    ) -> tuple[str | None, list[dict]]:
        """获取 `model context and append` 相关数据。"""
        if not messages:
            raise ValueError("messages 不能为空")

        current_time = self._now()
        connection = self._connect()
        connection.isolation_level = None  # 手动事务 避免隐式事务冲突
        try:
            connection.execute("BEGIN IMMEDIATE")

            exists = connection.execute(
                "SELECT 1 FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if exists is None:
                raise ValueError("对话不存在")

            summary: str | None = None
            summarized_through_message_id = 0
            if use_summary:
                summary_row = connection.execute(
                    """
                    SELECT summary, summarized_through_message_id
                    FROM conversation_summaries
                    WHERE conversation_id = ?
                    """,
                    (conversation_id,),
                ).fetchone()
                if summary_row is not None:
                    summary = str(summary_row["summary"])
                    summarized_through_message_id = int(
                        summary_row["summarized_through_message_id"]
                    )

            rows = connection.execute(
                """
                SELECT role, COALESCE(model_content, content) AS content, name
                FROM messages
                WHERE conversation_id = ? AND id > ?
                ORDER BY id ASC
                """,
                (conversation_id, summarized_through_message_id),
            ).fetchall()

            history: list[dict] = []
            for row in rows:
                message: dict = {
                    "role": row["role"],
                    "content": row["content"],
                }
                if row["name"] is not None:
                    message["name"] = row["name"]
                history.append(message)

            self._insert_messages(connection, conversation_id, messages, current_time)
            connection.execute(
                """
                UPDATE conversations
                SET updated_at = ?
                WHERE conversation_id = ?
                """,
                (current_time, conversation_id),
            )

            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return summary, history
