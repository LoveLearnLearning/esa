# backend/core/web/routers/auth.py

"""提供 `auth` 相关功能。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from backend.core.services.auth_service import AuthService
from backend.core.services.email_verification_service import (
    EmailDeliveryError,
    EmailVerificationService,
    InvalidEmail,
    normalize_email,
)
from backend.core.stores.email_verification_store import VerificationRateLimited
from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_presence_store import UserPresenceStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.deps import get_current_session
from backend.core.web.schemas import (
    BindEmailRequest,
    ChangePasswordRequest,
    EmailCodeRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]


def _email_service(request: Request) -> EmailVerificationService:
    """处理 `_email_service` 相关逻辑。"""
    service = getattr(request.app.state, "email_verification_service", None)
    if not isinstance(service, EmailVerificationService):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "邮件服务尚未配置",
        )
    return service


def _normalized_email(value: str) -> str:
    """处理 `_normalized_email` 相关逻辑。"""
    try:
        return normalize_email(value)
    except InvalidEmail as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error


def _client_ip(request: Request) -> str:
    """处理 `_client_ip` 相关逻辑。"""
    return request.client.host if request.client is not None else "unknown"


async def _send_code(
    *, request: Request, email: str, purpose: str
) -> dict[str, int | str]:
    """发送 `code` 相关数据。"""
    service = _email_service(request)
    try:
        retry_after = await service.request_code(
            email=email,
            purpose=purpose,
            ip=_client_ip(request),
        )
    except VerificationRateLimited as error:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "验证码发送过于频繁，请稍后再试",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    except EmailDeliveryError as error:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "邮件暂时无法投递，请稍后再试",
        ) from error
    return {"status": "accepted", "retry_after_seconds": retry_after}


def _require_valid_code(
    service: EmailVerificationService,
    *,
    email: str,
    purpose: str,
    code: str,
) -> None:
    """处理 `_require_valid_code` 相关逻辑。"""
    result = service.verify(email=email, purpose=purpose, code=code)
    if result == "expired":
        detail = "验证码已过期，请重新获取"
    elif result == "attempts_exceeded":
        detail = "验证码错误次数过多，请重新获取"
    elif result != "ok":
        detail = "验证码错误"
    else:
        return
    raise HTTPException(status.HTTP_400_BAD_REQUEST, detail)


@router.post("/email/send-code", status_code=status.HTTP_202_ACCEPTED)
async def send_registration_code(
    body: EmailCodeRequest,
    request: Request,
) -> dict[str, int | str]:
    """发送 `registration code` 相关数据。

    Args:
        body: EmailCodeRequest => `body` 参数。
        request: Request => 当前 HTTP 请求。

    Returns:
        dict[str, int | str] => 处理结果。
    """
    email = _normalized_email(body.email)
    user_store: UserStore = request.app.state.user_store
    if user_store.get_by_email(email) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该邮箱已注册")
    return await _send_code(request=request, email=email, purpose="register")


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, request: Request) -> dict[str, str]:
    """注册 `register` 相关数据。

    Args:
        body: RegisterRequest => `body` 参数。
        request: Request => 当前 HTTP 请求。

    Returns:
        dict[str, str] => 处理结果。
    """
    auth_service: AuthService = request.app.state.auth
    user_store: UserStore = request.app.state.user_store
    email = _normalized_email(body.email)
    if user_store.get_by_username(body.username) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")
    if user_store.get_by_email(email) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该邮箱已注册")
    email_service = _email_service(request)
    _require_valid_code(email_service, email=email, purpose="register", code=body.verification_code)
    verified_at = datetime.now(timezone.utc).isoformat()
    user: UserRecord | None = auth_service.register(
        body.username,
        body.password,
        body.account_role,
        email=email,
        email_verified_at=verified_at,
    )
    if user is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名或邮箱已存在")

    return {
        "user_id": user.id,
        "username": user.username,
        "email": email,
        "account_role": user.account_role,
    }


@router.post("/login")
def login(body: LoginRequest, request: Request) -> LoginResponse:
    """处理 `login` 相关逻辑。

    Args:
        body: LoginRequest => `body` 参数。
        request: Request => 当前 HTTP 请求。

    Returns:
        LoginResponse => 处理结果。
    """
    auth_service: AuthService = request.app.state.auth
    session: SessionPrincipal | None = auth_service.login(body.username, body.password)

    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "邮箱、用户名或密码错误")

    user_store: UserStore = request.app.state.user_store

    user: UserRecord | None = user_store.get_by_id(session.user_id)

    if user is None:
        session_store: SessionStore = request.app.state.session_store
        session_store.revoke(session.session_id)

        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")

    presence_store = getattr(request.app.state, "user_presence_store", None)
    if isinstance(presence_store, UserPresenceStore):
        presence_store.mark_online(session.user_id)

    return LoginResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        username=user.username,
        display_name=user.display_name or user.username,
        email=user.email,
        account_role=user.account_role,
        expires_at=session.expires_at,
    )


@router.post("/email/bind/send-code", status_code=status.HTTP_202_ACCEPTED)
async def send_bind_email_code(
    body: EmailCodeRequest,
    request: Request,
    session: CurrentSession,
) -> dict[str, int | str]:
    """发送 `bind email code` 相关数据。

    Args:
        body: EmailCodeRequest => `body` 参数。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict[str, int | str] => 处理结果。
    """
    del session
    email = _normalized_email(body.email)
    user_store: UserStore = request.app.state.user_store
    if user_store.get_by_email(email) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该邮箱已被其他账号使用")
    return await _send_code(request=request, email=email, purpose="bind")


@router.post("/email/bind")
def bind_email(
    body: BindEmailRequest,
    request: Request,
    session: CurrentSession,
) -> dict[str, str]:
    """处理 `bind_email` 相关逻辑。

    Args:
        body: BindEmailRequest => `body` 参数。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict[str, str] => 处理结果。
    """
    email = _normalized_email(body.email)
    user_store: UserStore = request.app.state.user_store
    existing = user_store.get_by_email(email)
    if existing is not None and existing.id != session.user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "该邮箱已被其他账号使用")
    email_service = _email_service(request)
    _require_valid_code(
        email_service,
        email=email,
        purpose="bind",
        code=body.verification_code,
    )
    if not user_store.bind_email(
        session.user_id,
        email,
        datetime.now(timezone.utc).isoformat(),
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "邮箱绑定失败")
    return {"email": email}


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def logout(request: Request, session: CurrentSession) -> None:
    """处理 `logout` 相关逻辑。

    Args:
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。
    """
    session_store: SessionStore = request.app.state.session_store
    session_store.revoke(session.session_id)
    presence_store = getattr(request.app.state, "user_presence_store", None)
    if isinstance(presence_store, UserPresenceStore):
        presence_store.mark_offline(session.user_id)
    compression_service = getattr(
        request.app.state,
        "conversation_compression_service",
        None,
    )
    if compression_service is not None:
        compression_service.wake()


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    session: CurrentSession,
) -> None:
    """处理 `change_password` 相关逻辑。

    Args:
        body: ChangePasswordRequest => `body` 参数。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。
    """
    auth_service: AuthService = request.app.state.auth

    try:
        changed = auth_service.change_password(
            user_id=session.user_id,
            old_password=body.old_password,
            new_password=body.new_password,
        )
    except ValueError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{error}") from error

    if not changed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "旧密码错误")

    session_store: SessionStore = request.app.state.session_store

    session_store.revoke_all_for_user(session.user_id)
