# backend/core/web/routers/workspaces.py

"""提供 `workspaces` 相关功能。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal
from backend.core.web.deps import get_current_session
from backend.core.workspaces import WorkspaceAccessPolicy

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]


@router.get("")
def get_workspace_manifest(
    request: Request,
    session: CurrentSession,
) -> dict[str, object]:
    """获取 `workspace manifest` 相关数据。

    Args:
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict[str, object] => 处理结果。
    """
    user_store: UserStore = request.app.state.user_store
    user = user_store.get_by_id(session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return WorkspaceAccessPolicy.manifest(user.account_role)
