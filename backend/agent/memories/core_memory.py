# backend/agent/memories/core_memory.py

import sqlite3
from datetime import datetime
from pathlib import Path


class CoreMemory:
    """
    核心记忆类

    将用户的喜好 习惯 兴趣等等存储到 sqlite 的 database 中供长期调用
    """

    def __init__(
        self,
        database_path: str | Path = "/data/core_memory.db",
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.__initialize()

    def __connect(self) -> sqlite3.Connection:
        """辅助函数 链接 SQLite 数据库"""
        connection: sqlite3.Connection = sqlite3.connect(
            self.database_path,
        )

        connection.row_factory = sqlite3.Row

        return connection

    def __initialize(self) -> None:
        """辅助函数 初始化 SQLite 数据库"""
        with self.__connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS core_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_name TEXT NOT NULL,
                    memory_key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_name, memory_key)
                )
                """
            )

    def set(
        self,
        user_name: str,
        memory_key: str,
        content: str,
        category: str = "general",
    ) -> bool:
        """在数据库中添加某条 core_memory
        Args:
            user_name: str             => 用户名
            memory_key: str            => 唯一的记忆 key 属性
            content: str               => 记忆内容
            category: str = "general"  => 记忆类别 默认为 "general"

        Returns:
            bool                       => 写入数据是否成功
        """
        user_name = user_name.strip()
        memory_key = memory_key.strip()
        content = content.strip()
        category = category.strip() or "general"

        if not user_name:
            return False

        if not memory_key:
            return False

        if not content:
            return False

        now = datetime.now().isoformat()

        with self.__connect() as connection:
            connection.execute(
                """
                INSERT INTO core_memories (
                    user_name,
                    memory_key,
                    content,
                    category,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_name, memory_key)
                DO UPDATE SET
                    content = excluded.content,
                    category = excluded.category,
                    updated_at = excluded.updated_at
                """,
                (
                    user_name,
                    memory_key,
                    content,
                    category,
                    now,
                    now,
                ),
            )

        return True

    def get(
        self,
        user_name: str,
        memory_key: str,
    ) -> dict[str, str | int] | None:
        """获取数据库中单条特定记忆
        Args:
            user_name: str              => 用户名
            memory_key: str             => 唯一的记忆 key 属性

        Returns:
            dict[str, str | int] | None:
                dict[str, str | int]    => 返回数据库中对应记忆:
                    K: str              => 字段
                    V: str | int        => 字段对应内容
                None                    => 没有该 memory_key 对应的记忆
        """

        with self.__connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    user_name,
                    memory_key,
                    content,
                    category,
                    created_at,
                    updated_at
                FROM core_memories
                WHERE user_name = ?
                  AND memory_key = ?
                """,
                (
                    user_name,
                    memory_key,
                ),
            ).fetchone()

        if row is None:
            return None

        return dict(row)

    def get_all(
        self,
        user_name: str,
    ) -> list[dict[str, str | int]]:
        """获取数据库中单个用户的所有 core_memories
        Args:
            user_name: str                => 用户名

        Returns:
            list[dict[str, str | int]]:
                dict[str, str | int]      => 返回数据库中对应记忆:
                        K: str            => 字段
                        V: str | int      => 字段对应内容
        """
        with self.__connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    user_name,
                    memory_key,
                    content,
                    category,
                    created_at,
                    updated_at
                FROM core_memories
                WHERE user_name = ?
                ORDER BY category ASC, updated_at DESC
                """,
                (user_name,),
            ).fetchall()

        return [dict(row) for row in rows]

    def delete(
        self,
        user_name: str,
        memory_key: str,
    ) -> bool:
        """删除用户对应 memory_key 的核心记忆
        Args:
            user_name: str  => 用户名
            memory_key: str => 唯一的记忆 key 属性

        Returns:
            bool            => 是否成功删除
        """
        with self.__connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM core_memories
                WHERE user_name = ?
                  AND memory_key = ?
                """,
                (
                    user_name,
                    memory_key,
                ),
            )

        return cursor.rowcount > 0

    def clear(self, user_name: str) -> int:
        """删除特定用户所有核心记忆
        Args:
            user_name: str  => 用户名

        Returns:
            int             => 剩余记忆数量
        """
        with self.__connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM core_memories
                WHERE user_name = ?
                """,
                (user_name,),
            )

        return cursor.rowcount

    def build_context(self, user_name: str) -> str:
        """使用用户核心记忆构造提示词
        Args:
            user_name: str  => 用户名:

        Returns:
            str             => 构造好的提示词
        """

        memories = self.get_all(user_name)

        if not memories:
            return "暂无核心记忆"

        return "\n".join(
            (f"- [{memory['category']}] {memory['memory_key']}  {memory['content']}")
            for memory in memories
        )
