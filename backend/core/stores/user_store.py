# backend/core/stores/user_store.py

"""提供数据持久化实现。"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore
from backend.core.utils.models import MemorySettings, UserRecord


class UserStore(BaseSQLiteStore):
    """
    用户表读写类
    """

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        """初始化 `UserStore` 实例。"""
        super().__init__(database_path)

    def _initialize(self) -> None:
        """辅助函数 初始化 users 表 并做老库迁移"""
        with closing(self._connect()) as connection, connection:
            # 新库直接建全 老库这条会被跳过
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    email TEXT COLLATE NOCASE,
                    email_verified_at TEXT,
                    password_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    account_role TEXT NOT NULL DEFAULT 'student',
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
            if "account_role" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN account_role TEXT NOT NULL DEFAULT 'student'"
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
            if "email" not in columns:
                connection.execute("ALTER TABLE users ADD COLUMN email TEXT")
            if "email_verified_at" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN email_verified_at TEXT"
                )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique
                ON users (email COLLATE NOCASE)
                WHERE email IS NOT NULL
                """
            )

            # 记忆与画像开关表 (spec Task 4) 实际存储细粒度开关
            # profile_enabled 已迁移到此表 拆分为 learning_profile_enabled + inferred_profile_enabled
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_settings (
                    user_id TEXT PRIMARY KEY,
                    saved_memory_enabled INTEGER NOT NULL DEFAULT 1,
                    chat_history_enabled INTEGER NOT NULL DEFAULT 1,
                    auto_extract_enabled INTEGER NOT NULL DEFAULT 0,
                    learning_profile_enabled INTEGER NOT NULL DEFAULT 1,
                    inferred_profile_enabled INTEGER NOT NULL DEFAULT 1,
                    default_conversation_mode TEXT NOT NULL DEFAULT 'normal',
                    episodic_retention_days INTEGER NOT NULL DEFAULT 180,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    CHECK(default_conversation_mode IN ('normal', 'no_write', 'isolated'))
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
        # learning_profile_enabled / inferred_profile_enabled 实际来自 memory_settings 表
        # 此处仅用 profile_enabled 作为回退值 真正的细粒度值需调用 get_memory_settings() 获取
        return UserRecord(
            id=row["id"],
            username=row["username"],
            password_hash=row["password_hash"],
            status=row["status"],
            account_role=row["account_role"],
            email=row["email"],
            email_verified_at=row["email_verified_at"],
            preferred_style=row["preferred_style"],
            preferred_tone=row["preferred_tone"],
            custom_instruction=row["custom_instruction"],
            major=row["major"],
            grade=row["grade"],
            current_week=row["current_week"],
            total_weeks=row["total_weeks"],
            profile_enabled=bool(row["profile_enabled"]),
            learning_profile_enabled=bool(row["profile_enabled"]),
            inferred_profile_enabled=bool(row["profile_enabled"]),
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
            SELECT id, username, email, email_verified_at, password_hash, status,
                   account_role,
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
            SELECT id, username, email, email_verified_at, password_hash, status,
                   account_role,
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

    def get_by_email(self, email: str) -> UserRecord | None:
        """按已规范化的邮箱地址查找用户（大小写不敏感）。"""
        row = self.query_one(
            """
            SELECT id, username, email, email_verified_at, password_hash, status,
                   account_role,
                   preferred_style, preferred_tone, custom_instruction,
                   major, grade, current_week, total_weeks, profile_enabled
            FROM users
            WHERE email = ? COLLATE NOCASE
            """,
            (email,),
        )
        return self.to_model(row) if row is not None else None

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
                    id, username, email, email_verified_at, password_hash, status,
                    account_role,
                    preferred_style, preferred_tone, custom_instruction,
                    major, grade, current_week, total_weeks, profile_enabled
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user.id,
                    user.username,
                    user.email,
                    user.email_verified_at,
                    user.password_hash,
                    user.status,
                    user.account_role,
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

    def bind_email(
        self,
        user_id: str,
        email: str,
        verified_at: str,
    ) -> bool:
        """给老用户绑定已验证邮箱；邮箱唯一性由数据库保证。"""
        try:
            count = self.execute(
                """
                UPDATE users
                SET email = ?, email_verified_at = ?
                WHERE id = ?
                """,
                (email, verified_at, user_id),
            )
        except sqlite3.IntegrityError:
            return False
        return count > 0

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

    def get_memory_settings(self, user_id: str) -> MemorySettings | None:
        """获取用户的记忆与画像开关设置 不存在则按老 profile_enabled 懒迁移建行

        迁移逻辑: 首次读取时若 memory_settings 无对应行 读 users.profile_enabled 派生
        profile_enabled=False => 两个细粒度开关都 False; True => 都 True

        Args:
            user_id: str => 用户 id

        Returns:
            MemorySettings | None:
                MemorySettings => 设置对象
                None           => 用户不存在
        """
        row = self.query_one(
            """
            SELECT user_id, saved_memory_enabled, chat_history_enabled, auto_extract_enabled,
                   learning_profile_enabled, inferred_profile_enabled,
                   default_conversation_mode, episodic_retention_days,
                   created_at, updated_at
            FROM memory_settings
            WHERE user_id = ?
            """,
            (user_id,),
        )

        if row is not None:
            return MemorySettings(
                user_id=row["user_id"],
                saved_memory_enabled=bool(row["saved_memory_enabled"]),
                chat_history_enabled=bool(row["chat_history_enabled"]),
                auto_extract_enabled=bool(row["auto_extract_enabled"]),
                learning_profile_enabled=bool(row["learning_profile_enabled"]),
                inferred_profile_enabled=bool(row["inferred_profile_enabled"]),
                default_conversation_mode=row["default_conversation_mode"],
                episodic_retention_days=row["episodic_retention_days"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

        # 不存在 走迁移逻辑 读老 profile_enabled 派生细粒度开关
        user_row = self.query_one(
            "SELECT profile_enabled FROM users WHERE id = ?",
            (user_id,),
        )
        if user_row is None:
            # 用户不存在
            return None

        profile_enabled = bool(user_row["profile_enabled"])
        learning_profile_enabled = profile_enabled
        inferred_profile_enabled = profile_enabled

        now_iso = datetime.now().isoformat()
        self.execute(
            """
            INSERT INTO memory_settings (
                user_id, saved_memory_enabled, chat_history_enabled, auto_extract_enabled,
                learning_profile_enabled, inferred_profile_enabled,
                default_conversation_mode, episodic_retention_days,
                created_at, updated_at
            )
            VALUES (?, 1, 1, 0, ?, ?, 'normal', 180, ?, ?)
            """,
            (
                user_id,
                int(learning_profile_enabled),
                int(inferred_profile_enabled),
                now_iso,
                now_iso,
            ),
        )

        return MemorySettings(
            user_id=user_id,
            learning_profile_enabled=learning_profile_enabled,
            inferred_profile_enabled=inferred_profile_enabled,
            default_conversation_mode="normal",
            episodic_retention_days=180,
            created_at=now_iso,
            updated_at=now_iso,
        )

    def update_memory_settings(
        self,
        user_id: str,
        saved_memory_enabled: bool | None = None,
        chat_history_enabled: bool | None = None,
        auto_extract_enabled: bool | None = None,
        learning_profile_enabled: bool | None = None,
        inferred_profile_enabled: bool | None = None,
        default_conversation_mode: str | None = None,
    ) -> bool:
        """部分更新用户记忆与画像开关 只更新非 None 的字段

        若 memory_settings 行不存在 先调 get_memory_settings 懒迁移建行再更新

        Args:
            user_id: str                                  => 用户 id
            learning_profile_enabled: bool | None = None  => 学习画像开关  None 表示不改
            inferred_profile_enabled: bool | None = None  => 推断画像开关  None 表示不改
            default_conversation_mode: str | None = None  => 默认会话模式  None 表示不改

        Returns:
            bool => 是否更新成功(用户存在且有字段被更新)
        """
        # 确保行存在 不存在则按老 profile_enabled 派生建行
        existing = self.get_memory_settings(user_id)
        if existing is None:
            # 用户不存在
            return False

        # 字段名到传入值的映射 跳过 None
        fields: dict[str, int | str] = {}
        if saved_memory_enabled is not None:
            fields["saved_memory_enabled"] = int(saved_memory_enabled)
        if chat_history_enabled is not None:
            fields["chat_history_enabled"] = int(chat_history_enabled)
        if auto_extract_enabled is not None:
            fields["auto_extract_enabled"] = int(auto_extract_enabled)
        if learning_profile_enabled is not None:
            fields["learning_profile_enabled"] = int(learning_profile_enabled)
        if inferred_profile_enabled is not None:
            fields["inferred_profile_enabled"] = int(inferred_profile_enabled)
        if default_conversation_mode is not None:
            fields["default_conversation_mode"] = default_conversation_mode

        if not fields:
            # 没有字段要更新 直接算成功
            return True

        # 总是更新 updated_at
        fields["updated_at"] = datetime.now().isoformat()

        set_clause = ", ".join(f"{name} = ?" for name in fields)
        params = (*fields.values(), user_id)

        count = self.execute(
            f"""
            UPDATE memory_settings
            SET {set_clause}
            WHERE user_id = ?
            """,
            params,
        )

        return count > 0
