# backend/agent/memories/core_memory.py

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class CoreMemory:
    """
    核心记忆数据层。

    只负责持久化、精确读取和按需检索，不负责构造 Prompt。
    Prompt 是否读取长期记忆由 Agent 的 Tool 调用策略决定。
    """

    def __init__(
        self,
        database_path: str | Path = "data/core_memory.db",
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.__initialize()

    def __connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
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
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_core_memories_user_updated
                ON core_memories(user_name, updated_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_core_memories_user_category
                ON core_memories(user_name, category)
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

        if not user_name or not memory_key or not content:
            return False

        now = datetime.now(timezone.utc).isoformat()
        with self.__connect() as connection:
            connection.execute(
                """
                INSERT INTO core_memories (
                    user_name, memory_key, content, category, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_name, memory_key)
                DO UPDATE SET
                    content = excluded.content,
                    category = excluded.category,
                    updated_at = excluded.updated_at
                """,
                (user_name, memory_key, content, category, now, now),
            )
        return True

    def get(
        self,
        user_name: str,
        memory_key: str,
    ) -> dict[str, str | int] | None:
        user_name = user_name.strip()
        memory_key = memory_key.strip()
        if not user_name or not memory_key:
            return None

        with self.__connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_name, memory_key, content, category, created_at, updated_at
                FROM core_memories
                WHERE user_name = ? AND memory_key = ?
                """,
                (user_name, memory_key),
            ).fetchone()
        return None if row is None else dict(row)

    def get_all(
        self,
        user_name: str,
    ) -> list[dict[str, str | int]]:
        user_name = user_name.strip()
        if not user_name:
            return []

        with self.__connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_name, memory_key, content, category, created_at, updated_at
                FROM core_memories
                WHERE user_name = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (user_name,),
            ).fetchall()
        return [dict(row) for row in rows]

    def search(
        self,
        user_name: str,
        query: str,
        *,
        category: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, str | int]]:
        """
        按需检索少量相关核心记忆。

        memory_key 精确/子串命中优先，其次 content/category 命中；
        同分时优先最近更新的记忆。没有任何文本命中时返回空列表，
        不回退成“把全部记忆塞给模型”。
        """
        user_name = user_name.strip()
        query = query.strip().lower()
        category = (category or "").strip().lower() or None
        limit = max(1, min(20, int(limit)))

        if not user_name or not query:
            return []

        memories = self.get_all(user_name)
        ranked: list[tuple[int, str, dict[str, str | int]]] = []
        terms = [part for part in query.split() if part]

        for memory in memories:
            memory_category = str(memory.get("category", "")).lower()
            if category is not None and memory_category != category:
                continue

            key = str(memory.get("memory_key", "")).lower()
            content = str(memory.get("content", "")).lower()
            score = 0

            if key == query:
                score += 12
            elif query in key:
                score += 8
            if query in content:
                score += 5
            if query == memory_category:
                score += 3

            for term in terms:
                if term == query:
                    continue
                if term in key:
                    score += 3
                if term in content:
                    score += 1

            if score > 0:
                ranked.append((score, str(memory.get("updated_at", "")), memory))

        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in ranked[:limit]]

    def delete(
        self,
        user_name: str,
        memory_key: str,
    ) -> bool:
        user_name = user_name.strip()
        memory_key = memory_key.strip()
        if not user_name or not memory_key:
            return False

        with self.__connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM core_memories
                WHERE user_name = ? AND memory_key = ?
                """,
                (user_name, memory_key),
            )
        return cursor.rowcount > 0

    def clear(self, user_name: str) -> int:
        user_name = user_name.strip()
        if not user_name:
            return 0

        with self.__connect() as connection:
            cursor = connection.execute(
                "DELETE FROM core_memories WHERE user_name = ?",
                (user_name,),
            )
        return cursor.rowcount
