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
    user_store: UserStore = request.app.state.user_store
    user = user_store.get_by_id(session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return WorkspaceAccessPolicy.manifest(user.account_role)
