# backend/core/web/deps.py

"""提供 `deps` 相关功能。"""


from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from fastapi import Header, HTTPException, Request

from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_presence_store import UserPresenceStore
from backend.core.utils.models import SessionPrincipal

logger = logging.getLogger(__name__)


def get_current_session(
    request: Request,
    authorization: str | None = Header(default=None),
) -> SessionPrincipal:
    """获取 `current session` 相关数据。

    Args:
        request: Request => 当前 HTTP 请求。
        authorization: str => `authorization` 参数。

    Returns:
        SessionPrincipal => 处理结果。
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(401, "格式错误")

    token = authorization.removeprefix("Bearer ").strip()

    session_store: SessionStore = request.app.state.session_store
    session: SessionPrincipal | None = session_store.get(token)

    if session is None:
        raise HTTPException(401, "会话无效")
    if session.expires_at <= datetime.now(timezone.utc):
        session_store.revoke(session.session_id)
        presence_store = getattr(request.app.state, "user_presence_store", None)
        if isinstance(presence_store, UserPresenceStore):
            try:
                presence_store.mark_offline(session.user_id)
            except sqlite3.Error:
                logger.warning("更新过期会话的离线状态失败", exc_info=True)
        raise HTTPException(401, "会话过期")

    presence_store = getattr(request.app.state, "user_presence_store", None)
    if isinstance(presence_store, UserPresenceStore):
        try:
            presence_store.mark_online(session.user_id)
        except sqlite3.Error:
            # Presence is advisory. A short SQLite lock must not reject a valid
            # authenticated request; active turn leases still protect chat writes.
            logger.warning("更新用户在线状态失败", exc_info=True)

    return session
