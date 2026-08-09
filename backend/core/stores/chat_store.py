# backend/core/stores/chat_store.py

from __future__ import annotations

import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


_UNSET = object()


class ChatStore(BaseSQLiteStore):
    """聊天记录读写类。"""

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        super().__init__(database_path)

    def _initialize(self) -> None:
        """初始化 conversations、messages 表并迁移旧数据库。"""
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    group_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY(group_id) REFERENCES groups(group_id) ON DELETE SET NULL
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
                    name TEXT,
                    is_visible INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
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
                connection.execute(
                    "ALTER TABLE conversations ADD COLUMN group_id TEXT"
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
        return datetime.now(timezone.utc).isoformat()

    def create_conversation(
        self,
        user_id: str,
        title: str = "新对话",
        group_id: str | None = None,
    ) -> dict:
        now = self._now()
        conversation: dict = {
            "conversation_id": str(uuid.uuid4()),
            "user_id": user_id,
            "title": title,
            "group_id": group_id,
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
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                conversation["conversation_id"],
                conversation["user_id"],
                conversation["title"],
                conversation["group_id"],
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
        sql = """
            SELECT conversation_id, user_id, title, group_id, created_at, updated_at
            FROM conversations
            WHERE conversation_id = ?
        """
        params: tuple = (conversation_id,)
        if user_id is not None:
            sql += " AND user_id = ?"
            params += (user_id,)

        row = self.query_one(sql, params)
        return dict(row) if row is not None else None

    def list_conversations(
        self,
        user_id: str,
        group_id: str | None = None,
        *,
        include_all_groups: bool = True,
    ) -> list[dict]:
        """列出用户对话。

        默认返回全部对话。传入 group_id 时仅返回该分组；若要查询未分组，
        传 group_id=None 且 include_all_groups=False。
        """
        sql = """
            SELECT conversation_id, user_id, title, group_id, created_at, updated_at
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

        sql += " ORDER BY updated_at DESC"
        return [dict(row) for row in self.query_all(sql, params)]

    def rename_conversation(
        self,
        conversation_id: str,
        title: str,
        user_id: str | None = None,
    ) -> bool:
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

        if not assignments:
            return self.get_conversation(
                conversation_id,
                user_id=user_id,
            ) is not None

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

    def append_messages(
        self,
        conversation_id: str,
        messages: list[dict],
    ) -> None:
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

            connection.executemany(
                """
                INSERT INTO messages (
                    conversation_id,
                    role,
                    content,
                    name,
                    is_visible,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        conversation_id,
                        message["role"],
                        message["content"],
                        message.get("name"),
                        1 if message.get("is_visible", True) else 0,
                        current_time,
                    )
                    for message in messages
                ],
            )
            connection.execute(
                """
                UPDATE conversations
                SET updated_at = ?
                WHERE conversation_id = ?
                """,
                (current_time, conversation_id),
            )

    def get_history(self, conversation_id: str) -> list[dict]:
        rows = self.query_all(
            """
            SELECT id, role, content, name, created_at
            FROM messages
            WHERE conversation_id = ?
              AND is_visible = 1
            ORDER BY id ASC
            """,
            (conversation_id,),
        )
        return [dict(row) for row in rows]

    def get_model_messages(self, conversation_id: str) -> list[dict]:
        rows = self.query_all(
            """
            SELECT role, content, name
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

            rows = connection.execute(
                """
                SELECT role, content, name
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id ASC
                """,
                (conversation_id,),
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

            connection.executemany(
                """
                INSERT INTO messages (
                    conversation_id,
                    role,
                    content,
                    name,
                    is_visible,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        conversation_id,
                        message["role"],
                        message["content"],
                        message.get("name"),
                        1 if message.get("is_visible", True) else 0,
                        current_time,
                    )
                    for message in messages
                ],
            )
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

        return history
