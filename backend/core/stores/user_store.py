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
        """辅助函数 初始化 users 表 并做老库迁移"""
        with self._connect() as connection:
            # 新库直接建全 老库这条会被跳过
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    preferred_style TEXT NOT NULL DEFAULT 'concise',
                    preferred_tone TEXT NOT NULL DEFAULT 'friendly',
                    custom_instruction TEXT NOT NULL DEFAULT '',
                    major TEXT NOT NULL DEFAULT 'cs',
                    grade TEXT NOT NULL DEFAULT '',
                    current_week INTEGER NOT NULL DEFAULT 1,
                    total_weeks INTEGER NOT NULL DEFAULT 18,
                    profile_enabled INTEGER NOT NULL DEFAULT 1
                )
                """
            )

            # 老库迁移 检查每个新列是否存在 不在就补上
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }

            if "preferred_style" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN preferred_style TEXT NOT NULL DEFAULT 'concise'"
                )
            if "preferred_tone" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN preferred_tone TEXT NOT NULL DEFAULT 'friendly'"
                )
            if "custom_instruction" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN custom_instruction TEXT NOT NULL DEFAULT ''"
                )
            # 学生档案字段
            if "major" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN major TEXT NOT NULL DEFAULT 'cs'"
                )
            if "grade" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN grade TEXT NOT NULL DEFAULT ''"
                )
            if "current_week" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN current_week INTEGER NOT NULL DEFAULT 1"
                )
            if "total_weeks" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN total_weeks INTEGER NOT NULL DEFAULT 18"
                )
            if "profile_enabled" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN profile_enabled INTEGER NOT NULL DEFAULT 1"
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
            preferred_style=row["preferred_style"],
            preferred_tone=row["preferred_tone"],
            custom_instruction=row["custom_instruction"],
            major=row["major"],
            grade=row["grade"],
            current_week=row["current_week"],
            total_weeks=row["total_weeks"],
            profile_enabled=bool(row["profile_enabled"]),
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
            SELECT id, username, password_hash, status,
                   preferred_style, preferred_tone, custom_instruction,
                   major, grade, current_week, total_weeks, profile_enabled
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
            SELECT id, username, password_hash, status,
                   preferred_style, preferred_tone, custom_instruction,
                   major, grade, current_week, total_weeks, profile_enabled
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
                INSERT INTO users (
                    id, username, password_hash, status,
                    preferred_style, preferred_tone, custom_instruction,
                    major, grade, current_week, total_weeks, profile_enabled
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user.id,
                    user.username,
                    user.password_hash,
                    user.status,
                    user.preferred_style,
                    user.preferred_tone,
                    user.custom_instruction,
                    user.major,
                    user.grade,
                    user.current_week,
                    user.total_weeks,
                    int(user.profile_enabled),
                ),
            )
        except sqlite3.IntegrityError:
            return False

        return True

    def update_password(self, user_id: str, password_hash: str) -> bool:
        """更新用户密码的哈希值

        Args:
            user_id: str        => 用户 id
            password_hash: str  => 更改的目标密码哈希值

        Returns:
            bool                => 是否修改成功
        """
        count = self.execute(
            """
            UPDATE users
            SET password_hash = ?
            WHERE id = ?
            """,
            (
                password_hash,
                user_id,
            ),
        )

        return count > 0

    def update_preferences(
        self,
        user_id: str,
        preferred_style: str | None = None,
        preferred_tone: str | None = None,
        custom_instruction: str | None = None,
    ) -> bool:
        """部分更新用户偏好 只更新非 None 的字段

        Args:
            user_id: str                        => 用户 id
            preferred_style: str | None = None  => 风格  None 表示不改
            preferred_tone: str | None = None   => 语调  None 表示不改
            custom_instruction: str | None = None => 自定义指令  None 表示不改

        Returns:
            bool => 是否更新成功(用户存在且有字段被更新)
        """
        # 字段名到传入值的映射 跳过 None
        fields: dict[str, str] = {}
        if preferred_style is not None:
            fields["preferred_style"] = preferred_style
        if preferred_tone is not None:
            fields["preferred_tone"] = preferred_tone
        if custom_instruction is not None:
            fields["custom_instruction"] = custom_instruction

        if not fields:
            # 没有字段要更新 直接算成功
            return True

        set_clause = ", ".join(f"{name} = ?" for name in fields)
        params = (*fields.values(), user_id)

        count = self.execute(
            f"""
            UPDATE users
            SET {set_clause}
            WHERE id = ?
            """,
            params,
        )

        return count > 0

    def update_profile(
        self,
        user_id: str,
        major: str | None = None,
        grade: str | None = None,
        current_week: int | None = None,
        total_weeks: int | None = None,
        profile_enabled: bool | None = None,
    ) -> bool:
        """部分更新用户学习档案 只更新非 None 的字段

        与 update_preferences 分开 学习档案字段语义独立
        路由层负责校验 major 枚举 / current_week <= total_weeks 等约束

        Args:
            user_id: str                        => 用户 id
            major: str | None = None            => 专业  None 表示不改
            grade: str | None = None            => 年级  None 表示不改
            current_week: int | None = None     => 当前教学周  None 表示不改
            total_weeks: int | None = None      => 学期总周数  None 表示不改
            profile_enabled: bool | None = None => 用户画像开关  None 表示不改

        Returns:
            bool => 是否更新成功(用户存在且有字段被更新)
        """
        # 字段名到传入值的映射 跳过 None
        fields: dict[str, str | int] = {}
        if major is not None:
            fields["major"] = major
        if grade is not None:
            fields["grade"] = grade
        if current_week is not None:
            fields["current_week"] = current_week
        if total_weeks is not None:
            fields["total_weeks"] = total_weeks
        if profile_enabled is not None:
            fields["profile_enabled"] = int(profile_enabled)

        if not fields:
            # 没有字段要更新 直接算成功
            return True

        set_clause = ", ".join(f"{name} = ?" for name in fields)
        params = (*fields.values(), user_id)

        count = self.execute(
            f"""
            UPDATE users
            SET {set_clause}
            WHERE id = ?
            """,
            params,
        )

        return count > 0
