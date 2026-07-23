# backend/core/stores/user_store.py

import sqlite3
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore
from backend.core.utils.models import UserRecord


class UserStore(BaseSQLiteStore):
    """
    用户表读写类
    """

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        super().__init__(database_path)

    def _initialize(self) -> None:
        """辅助函数 初始化 users 表"""
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            )
            """
        )

    def to_model(self, row: sqlite3.Row) -> UserRecord:
        """将数据库记录转化为实例对象
        Args:
            row: sqlite3.Row => 用户表中的一行记录

        Returns:
            UserRecord       => 用户数据对象
        """
        return UserRecord(
            id=row["id"],
            username=row["username"],
            password_hash=row["password_hash"],
            status=row["status"],
        )

    def get_by_id(self, user_id: str) -> UserRecord | None:
        """通过用户 id 获取用户
        Args:
            user_id: str => 用户 id

        Returns:
            UserRecord | None:
                UserRecord => 用户数据对象
                None       => 用户不存在
        """
        row = self.query_one(
            """
            SELECT id, username, password_hash, status
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        )

        if row is None:
            return None

        return self.to_model(row)

    def get_by_username(self, username: str) -> UserRecord | None:
        """通过用户名获取用户
        Args:
            username: str => 用户名

        Returns:
            UserRecord | None:
                UserRecord => 用户数据对象
                None       => 用户不存在
        """
        row = self.query_one(
            """
            SELECT id, username, password_hash, status
            FROM users
            WHERE username = ?
            """,
            (username,),
        )

        if row is None:
            return None

        return self.to_model(row)

    def create(self, user: UserRecord) -> bool:
        """创建新用户
        Args:
            user: UserRecord => 要创建的用户数据对象

        Returns:
            bool             => 是否创建成功 用户 id 或用户名已存在时返回 False
        """
        try:
            self.execute(
                """
                INSERT INTO users (id, username, password_hash, status)
                VALUES (?, ?, ?, ?)
                """,
                (
                    user.id,
                    user.username,
                    user.password_hash,
                    user.status,
                ),
            )
        except sqlite3.IntegrityError:
            return False

        return True
