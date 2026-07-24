# backend/core/web/deps.py

from datetime import UTC, datetime

from fastapi import Header, HTTPException, Request

from backend.core.stores.session_store import SessionStore
from backend.core.utils.models import SessionPrincipal


def get_current_session(
    request: Request,
    authorization: str = Header(...),
) -> SessionPrincipal:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bro 我通你滴木马 你个表把格式搞错了！！！")

    token = authorization.removeprefix("Bearer ").strip()

    session_store: SessionStore = request.app.state.session_store
    session: SessionPrincipal | None = session_store.get(token)

    if session is None:
        raise HTTPException(401, "Bro 我通你滴木马 你个表的会话是无效的！！！")
    if session.expires_at <= datetime.now(UTC):
        session_store.revoke(session.session_id)
        raise HTTPException(401, "Bro 你个表滴会话早过期了！！")

    return session
