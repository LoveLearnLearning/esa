# backend/core/web/routers/auth.py

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.core.services.auth_service import AuthService
from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_presence_store import UserPresenceStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.deps import get_current_session
from backend.core.web.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, request: Request) -> dict[str, str]:
    auth_service: AuthService = request.app.state.auth
    user: UserRecord | None = auth_service.register(body.username, body.password)
    if user is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")

    return {
        "user_id": user.id,
        "username": user.username,
    }


@router.post("/login")
def login(body: LoginRequest, request: Request) -> LoginResponse:
    auth_service: AuthService = request.app.state.auth
    session: SessionPrincipal | None = auth_service.login(body.username, body.password)

    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误！")

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
        expires_at=session.expires_at,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, session: CurrentSession) -> None:
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
)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    session: CurrentSession,
) -> None:
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
