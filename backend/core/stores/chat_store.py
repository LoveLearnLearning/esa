# backend/core/stores/chat_store.py

import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


class ChatStore(BaseSQLiteStore):
    """
    聊天记录读写类

    conversations 表存历史对话列表 messages 表存每个对话内的消息
    方法统一返回 dict 方便 FastAPI 直接序列化成 JSON 返回给前端
    """

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        super().__init__(database_path)

    def _initialize(self) -> None:
        """辅助函数 初始化 conversations 和 messages 表"""
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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
                    created_at TEXT NOT NULL
                )
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

    @staticmethod
    def _now() -> str:
        """辅助函数 当前 UTC 时间的 ISO 字符串"""
        return datetime.now(UTC).isoformat()

    def create_conversation(
        self,
        user_id: str,
        title: str = "新对话",
    ) -> dict:
        """创建一个新对话
        Args:
            user_id: str          => 用户 id
            title: str = "新对话" => 对话标题 默认为 "新对话"

        Returns:
            dict                  => 新建对话的完整信息
        """
        conversation: dict = {
            "conversation_id": str(uuid.uuid4()),
            "user_id": user_id,
            "title": title,
            "created_at": self._now(),
            "updated_at": self._now(),
        }

        self.execute(
            """
            INSERT INTO conversations (
                conversation_id,
                user_id,
                title,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                conversation["conversation_id"],
                conversation["user_id"],
                conversation["title"],
                conversation["created_at"],
                conversation["updated_at"],
            ),
        )

        return conversation

    def get_conversation(self, conversation_id: str) -> dict | None:
        """获取单个对话的信息
        Args:
            conversation_id: str => 对话 id

        Returns:
            dict | None:
                dict => 对话信息
                None => 对话不存在
        """
        row = self.query_one(
            """
            SELECT conversation_id, user_id, title, created_at, updated_at
            FROM conversations
            WHERE conversation_id = ?
            """,
            (conversation_id,),
        )

        if row is None:
            return None

        return dict(row)

    def list_conversations(self, user_id: str) -> list[dict]:
        """获取用户的历史对话列表 按最近更新排序
        Args:
            user_id: str => 用户 id

        Returns:
            list[dict]   => 对话信息列表 最近更新的排在前面
        """
        rows = self.query_all(
            """
            SELECT conversation_id, user_id, title, created_at, updated_at
            FROM conversations
            WHERE user_id = ?
            ORDER BY updated_at DESC
            """,
            (user_id,),
        )

        return [dict(row) for row in rows]

    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        """重命名对话
        Args:
            conversation_id: str => 对话 id
            title: str           => 新标题

        Returns:
            bool                 => 是否重命名成功 对话不存在时返回 False
        """
        count: int = self.execute(
            """
            UPDATE conversations
            SET title = ?, updated_at = ?
            WHERE conversation_id = ?
            """,
            (title, self._now(), conversation_id),
        )

        return count > 0

    def delete_conversation(self, conversation_id: str) -> bool:
        """删除对话及其所有消息
        Args:
            conversation_id: str => 对话 id

        Returns:
            bool                 => 是否删除成功 对话不存在时返回 False
        """
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                DELETE FROM messages
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            )
            cursor = connection.execute(
                """
                DELETE FROM conversations
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            )

        return cursor.rowcount > 0

    def append_messages(
        self,
        conversation_id: str,
        messages: list[dict],
    ) -> None:
        """向对话中追加消息 同时刷新对话的更新时间
        Args:
            conversation_id: str  => 对话 id
            messages: list[dict]  => 消息列表 每条包含 role content
                                     tool 消息可以额外带 name 字段
        """
        current_time: str = self._now()

        with closing(self._connect()) as connection, connection:
            connection.executemany(
                """
                INSERT INTO messages (
                    conversation_id,
                    role,
                    content,
                    name,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        conversation_id,
                        message["role"],
                        message["content"],
                        message.get("name"),
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
        """读取对话的完整历史消息 按时间顺序排列
        Args:
            conversation_id: str => 对话 id

        Returns:
            list[dict]           => 消息列表 每条包含 id role content name created_at
        """
        rows = self.query_all(
            """
            SELECT id, role, content, name, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        )

        return [dict(row) for row in rows]

    def get_model_messages(self, conversation_id: str) -> list[dict]:
        """读取可以直接喂给模型的历史消息

        只保留 role content (tool 消息带 name) 去掉数据库相关字段

        Args:
            conversation_id: str => 对话 id

        Returns:
            list[dict]           => 模型格式的消息列表
        """
        model_messages: list[dict] = []

        for message in self.get_history(conversation_id):
            item: dict = {
                "role": message["role"],
                "content": message["content"],
            }
            if message["name"] is not None:
                item["name"] = message["name"]

            model_messages.append(item)

        return model_messages
