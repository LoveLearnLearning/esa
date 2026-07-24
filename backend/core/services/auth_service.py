# backend/core/services/auth_service.py

import uuid
from datetime import UTC, datetime, timedelta

from backend.core.services.password_service import PasswordService
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

        user: UserRecord | None = self.user_store.get_by_username(username)
        if not user:
            return
        login_state: bool = PasswordService.verify_password(
            password, user.password_hash
        )
        if not login_state:
            return

        session_id = str(uuid.uuid4())

        current_time = datetime.now(UTC)
        expire_time = current_time + timedelta(hours=2)
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

        pwd_hash = PasswordService.hash_password(password)
        new_user = UserRecord(
            id=str(uuid.uuid4()),
            username=username,
            password_hash=pwd_hash,
            status="active",
        )

        if not self.user_store.create(new_user):
            return None

        return new_user
