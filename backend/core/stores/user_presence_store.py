# backend/core/stores/user_presence_store.py

"""提供数据持久化实现。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


class UserPresenceStore(BaseSQLiteStore):
    """Persistent activity timestamps used to detect offline users."""

    def __init__(self, database_path: str | Path) -> None:
        """初始化 `UserPresenceStore` 实例。"""
        super().__init__(database_path)

    def _initialize(self) -> None:
        """初始化 `initialize` 相关数据。"""
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS user_presence (
                user_id TEXT PRIMARY KEY,
                is_online INTEGER NOT NULL DEFAULT 0,
                last_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )

    @staticmethod
    def _now() -> str:
        """处理 `_now` 相关逻辑。"""
        return datetime.now(timezone.utc).isoformat()

    def mark_online(self, user_id: str) -> None:
        """处理 `mark_online` 相关逻辑。

        Args:
            user_id: str => 用户 ID。
        """
        now = self._now()
        self.execute(
            """
            INSERT INTO user_presence (user_id, is_online, last_seen_at, updated_at)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                is_online = 1,
                last_seen_at = excluded.last_seen_at,
                updated_at = excluded.updated_at
            """,
            (user_id, now, now),
        )

    def mark_offline(self, user_id: str) -> None:
        """处理 `mark_offline` 相关逻辑。

        Args:
            user_id: str => 用户 ID。
        """
        now = self._now()
        self.execute(
            """
            INSERT INTO user_presence (user_id, is_online, last_seen_at, updated_at)
            VALUES (?, 0, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                is_online = 0,
                last_seen_at = excluded.last_seen_at,
                updated_at = excluded.updated_at
            """,
            (user_id, now, now),
        )
