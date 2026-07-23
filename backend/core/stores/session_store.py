# backend/core/stores/session_store.py

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore
from backend.core.utils.models import SessionPrincipal


class SessionStore(BaseSQLiteStore):
    """
    会话表读写类

    所有时间统一以 UTC ISO 格式字符串存储 同格式下可以直接按字符串比较大小
    """

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        super().__init__(database_path)

    def _initialize(self) -> None:
        """辅助函数 初始化 sessions 表"""
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                issued_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )

    def to_model(self, row: sqlite3.Row) -> SessionPrincipal:
        """将数据库记录转化为实例对象
        Args:
            row: sqlite3.Row => 会话表中的一行记录

        Returns:
            SessionPrincipal => 生命周期对象
        """
        return SessionPrincipal(
            session_id=row["session_id"],
            user_id=row["user_id"],
            issued_at=datetime.fromisoformat(row["issued_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
        )

    def get(self, session_id: str) -> SessionPrincipal | None:
        """通过 session_id 来获取生命周期内用户对象
        Args:
            session_id: str => 用户会话 id

        Returns:
            SessionPrincipal | None:
                SessionPrincipal => 生命周期内实例化用户信息
                None             => 会话不存在
        """
        row = self.query_one(
            """
            SELECT session_id, user_id, issued_at, expires_at
            FROM sessions
            WHERE session_id = ?
            """,
            (session_id,),
        )

        if row is None:
            return None

        return self.to_model(row)

    def create(self, session: SessionPrincipal) -> None:
        """登录时创建新会话 已存在时覆盖更新
        Args:
            session: SessionPrincipal => 要创建用户会话的实例对象
        """
        self.execute(
            """
            INSERT INTO sessions (session_id, user_id, issued_at, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id)
            DO UPDATE SET
                user_id = excluded.user_id,
                issued_at = excluded.issued_at,
                expires_at = excluded.expires_at
            """,
            (
                session.session_id,
                session.user_id,
                session.issued_at.isoformat(),
                session.expires_at.isoformat(),
            ),
        )

    def revoke(self, session_id: str) -> None:
        """用户退出登录时注销会话
        Args:
            session_id: str => 生命周期结束的用户会话
        """
        self.execute(
            """
            DELETE FROM sessions
            WHERE session_id = ?
            """,
            (session_id,),
        )

    def cleanup_expired(self) -> int:
        """清理过期会话
        Returns:
            int => 清除掉的过期会话数量
        """
        current_time: str = datetime.now(UTC).isoformat()

        return self.execute(
            """
            DELETE FROM sessions
            WHERE expires_at <= ?
            """,
            (current_time,),
        )
