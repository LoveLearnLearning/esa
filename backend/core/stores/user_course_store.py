# backend/core/stores/user_course_store.py

"""提供数据持久化实现。"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


class UserCourseStore(BaseSQLiteStore):
    """Store user/course associations without copying canonical KG data."""

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        """初始化 `UserCourseStore` 实例。"""
        super().__init__(database_path)

    def _initialize(self) -> None:
        """初始化 `initialize` 相关数据。"""
        with closing(self._connect()) as connection, connection:
            connection.execute(
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
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_courses_user_id "
                "ON user_courses(user_id)"
            )

    def list_for_user(self, user_id: str) -> list[dict]:
        """列出 `for user` 相关数据。"""
        rows = self.query_all(
            """
            SELECT name, canonical_course, source, created_at, updated_at
            FROM user_courses
            WHERE user_id = ?
            ORDER BY created_at, name
            """,
            (user_id,),
        )
        return [dict(row) for row in rows]

    def upsert(
        self,
        *,
        user_id: str,
        name: str,
        canonical_course: str | None,
        source: str,
    ) -> bool:
        """处理 `upsert` 相关逻辑。

        Args:
            user_id: str => 用户 ID。
            name: str => `name` 参数。
            canonical_course: str | None => `canonical_course` 参数。
            source: str => `source` 参数。

        Returns:
            bool => 处理结果。
        """
        clean_name = name.strip()
        if not clean_name or source not in {"manual", "timetable"}:
            return False
        now = datetime.now(timezone.utc).isoformat()
        self.execute(
            """
            INSERT INTO user_courses (
                user_id, name, canonical_course, source, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, name) DO UPDATE SET
                canonical_course = excluded.canonical_course,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (user_id, clean_name, canonical_course, source, now, now),
        )
        return True

    def delete(self, *, user_id: str, name: str) -> bool:
        """删除 `delete` 相关数据。

        Args:
            user_id: str => 用户 ID。
            name: str => `name` 参数。

        Returns:
            bool => 处理结果。
        """
        return (
            self.execute(
                "DELETE FROM user_courses WHERE user_id = ? AND name = ?",
                (user_id, name.strip()),
            )
            > 0
        )
