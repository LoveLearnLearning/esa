from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.core.stores.research_project_store import ResearchProjectStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal
from backend.core.web.deps import get_current_session
from backend.core.web.schemas import (
    ResearchProjectCreateRequest,
    ResearchProjectUpdateRequest,
)
from backend.core.workspaces import WorkspaceAccessPolicy

router = APIRouter(prefix="/research", tags=["research"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]


def _require_research_access(request: Request, user_id: str) -> None:
    user_store: UserStore = request.app.state.user_store
    user = user_store.get_by_id(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    if not WorkspaceAccessPolicy.can_access(user.account_role, "research"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权进入科研空间")


@router.get("/projects")
def list_projects(
    request: Request,
    session: CurrentSession,
    include_archived: bool = False,
) -> list[dict]:
    _require_research_access(request, session.user_id)
    store: ResearchProjectStore = request.app.state.research_project_store
    return store.list_projects(
        session.user_id,
        include_archived=include_archived,
    )


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(
    body: ResearchProjectCreateRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    _require_research_access(request, session.user_id)
    store: ResearchProjectStore = request.app.state.research_project_store
    return store.create_project(session.user_id, body.name, body.description)


@router.get("/projects/{project_id}")
def get_project(
    project_id: str,
    request: Request,
    session: CurrentSession,
) -> dict:
    _require_research_access(request, session.user_id)
    store: ResearchProjectStore = request.app.state.research_project_store
    project = store.get_project(project_id, session.user_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "科研项目不存在")
    return project


@router.patch("/projects/{project_id}")
def update_project(
    project_id: str,
    body: ResearchProjectUpdateRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    _require_research_access(request, session.user_id)
    store: ResearchProjectStore = request.app.state.research_project_store
    project = store.update_project(
        project_id,
        session.user_id,
        **body.model_dump(exclude_unset=True),
    )
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "科研项目不存在")
    return project
