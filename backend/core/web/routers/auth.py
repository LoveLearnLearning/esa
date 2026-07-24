# backend/core/web/routers/auth.py

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.core.services.auth_service import AuthService
from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.deps import get_current_session
from backend.core.web.schemas import LoginRequest, LoginResponse, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])


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

    assert user is not None

    return LoginResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        username=user.username,
        expires_at=session.expires_at,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, session=Depends(get_current_session)):
    session_store: SessionStore = request.app.state.session_store
    session_store.revoke(session.session_id)
