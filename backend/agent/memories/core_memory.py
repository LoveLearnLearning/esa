# backend/agent/memories/core_memory.py

import sqlite3
from datetime import datetime
from pathlib import Path


class CoreMemory:
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
        connection: sqlite3.Connection = sqlite3.connect(
            self.database_path,
        )

        connection.row_factory = sqlite3.Row

        return connection

    def __initialize(self) -> None:
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
        memories = self.get_all(user_name)

        if not memories:
            return "暂无核心记忆"

        return "\n".join(
            (f"- [{memory['category']}] {memory['memory_key']}  {memory['content']}")
            for memory in memories
        )
