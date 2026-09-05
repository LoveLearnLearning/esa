# backend/core/services/auth_service.py

"""提供领域服务实现。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from backend.core.services.password_service import PasswordService
from backend.core.services.email_verification_service import (
    InvalidEmail,
    normalize_email,
)
from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal, UserRecord


class AuthService:
    """
    验证服务类，用来解析用户登陆以及构建 Runtime Session
    """

    def __init__(
        self,
        user_store: UserStore,
        session_store: SessionStore,
    ) -> None:

        """初始化 `AuthService` 实例。"""
        self.user_store = user_store
        self.session_store = session_store

    def login(
        self,
        username: str,
        password: str,
    ) -> SessionPrincipal | None:
        """登陆接口 通过用户名和密码验证并签发会话
        Args:
            username: str => 用户名
            password: str => 用户输入的密码

        Returns:
            SessionPrincipal | None:
                SessionPrincipal => 登陆成功返回 RuntimeSession 数据对象
                None             => 登陆失败 用户不存在或密码错误
        """

        user: UserRecord | None
        if "@" in username:
            try:
                user = self.user_store.get_by_email(normalize_email(username))
            except InvalidEmail:
                user = None
            if user is None:
                # Legacy usernames were not restricted from containing '@'.
                user = self.user_store.get_by_username(username)
        else:
            user = self.user_store.get_by_username(username)
        if not user:
            return
        login_state: bool = PasswordService.verify_password(
            password, user.password_hash
        )
        if not login_state:
            return
        if user.status != "active":
            return

        session_id = str(uuid.uuid4())

        current_time = datetime.now(timezone.utc)
        expire_time = current_time + timedelta(days=7)
        session: SessionPrincipal = SessionPrincipal(
            session_id=session_id,
            user_id=user.id,
            issued_at=current_time,
            expires_at=expire_time,
        )
        self.session_store.create(session)

        return session

    def register(
        self,
        username: str,
        password: str,
        account_role: str = "student",
        *,
        email: str | None = None,
        email_verified_at: str | None = None,
    ) -> UserRecord | None:
        """给新用户提供注册服务 user_id 由服务端生成
        Args:
            username: str => 用户名
            password: str => 密码

        Returns:
            UserRecord | None:
                UserRecord => 注册成功返回新用户数据对象
                None       => 注册失败 用户名已存在
        """

        if self.user_store.get_by_username(username) is not None:
            return None
        if email is not None and self.user_store.get_by_email(email) is not None:
            return None

        pwd_hash = PasswordService.hash_password(password)
        new_user = UserRecord(
            id=str(uuid.uuid4()),
            username=username,
            password_hash=pwd_hash,
            status="active",
            account_role=account_role,
            email=email,
            email_verified_at=email_verified_at,
        )

        if not self.user_store.create(new_user):
            return None

        return new_user

    def change_password(
        self,
        user_id: str,
        old_password: str,
        new_password: str,
    ) -> bool:
        """修改密码

        Args:
            user_id: str        => 用户 id
            old_password: str   => 旧密码
            new_password: str   => 新密码

        Returns:
            bool                => 是否修改成功
        """

        user: UserRecord | None = self.user_store.get_by_id(user_id)

        if user is None:
            return False

        if not PasswordService.verify_password(
            old_password,
            user.password_hash,
        ):
            return False

        if PasswordService.verify_password(
            new_password,
            user.password_hash,
        ):
            raise ValueError("新密码不能与旧密码相同")

        new_password_hash = PasswordService.hash_password(new_password)

        return self.user_store.update_password(user_id, new_password_hash)
