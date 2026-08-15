# backend/core/web/routers/research.py

"""提供 `research` 相关功能。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.core.stores.research_project_store import ResearchProjectStore
from backend.core.stores.frontier_tracking_store import FrontierTrackingStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal
from backend.core.web.deps import get_current_session
from backend.core.web.schemas import (
    ResearchProjectCreateRequest,
    ResearchProjectUpdateRequest,
    FrontierTrackingCreateRequest,
    ResearchProjectProfileUpdateRequest,
)
from backend.agent.memories.core_memory_models import MemoryRevisionConflict
from backend.core.workspaces import WorkspaceAccessPolicy
from backend.core.workflows.research import ResearchWorkflowFacade

router = APIRouter(prefix="/research", tags=["research"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]


def _workflow_facade(request: Request) -> ResearchWorkflowFacade:
    """处理 `_workflow_facade` 相关逻辑。"""
    facade = getattr(request.app.state, "research_workflow_facade", None)
    if facade is not None:
        return facade
    return ResearchWorkflowFacade(
        project_store=request.app.state.research_project_store,
        frontier_store=request.app.state.frontier_tracking_store,
        frontier_service=request.app.state.frontier_tracking_service,
        writing_store=getattr(request.app.state, "research_writing_store", None),
        writing_service=getattr(request.app.state, "research_writing_service", None),
        data_store=getattr(request.app.state, "research_data_store", None),
        data_service=getattr(request.app.state, "research_data_service", None),
    )


def _require_research_access(request: Request, user_id: str) -> None:
    """处理 `_require_research_access` 相关逻辑。"""
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
    """列出 `projects` 相关数据。

    Args:
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。
        include_archived: bool => `include_archived` 参数。

    Returns:
        list[dict] => 处理结果。
    """
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
    """创建 `project` 相关数据。

    Args:
        body: ResearchProjectCreateRequest => `body` 参数。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    _require_research_access(request, session.user_id)
    store: ResearchProjectStore = request.app.state.research_project_store
    return store.create_project(session.user_id, body.name, body.description)


@router.get("/projects/{project_id}")
def get_project(
    project_id: str,
    request: Request,
    session: CurrentSession,
) -> dict:
    """获取 `project` 相关数据。

    Args:
        project_id: str => 项目 ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
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
    """更新 `project` 相关数据。

    Args:
        project_id: str => 项目 ID。
        body: ResearchProjectUpdateRequest => `body` 参数。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
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


@router.get("/projects/{project_id}/profile")
def get_project_profile(project_id: str, request: Request, session: CurrentSession) -> dict:
    """获取 `project profile` 相关数据。

    Args:
        project_id: str => 项目 ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    _require_research_access(request, session.user_id)
    service = request.app.state.research_project_profile_service
    try:
        return service.get(project_id, session.user_id) or {
            "project_id": project_id,
            "user_id": session.user_id,
            "agent_instructions": "",
            "format_version": 1,
            "revision": 0,
        }
    except KeyError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "科研项目不存在") from error


@router.put("/projects/{project_id}/profile")
def update_project_profile(project_id: str, body: ResearchProjectProfileUpdateRequest,
                           request: Request, session: CurrentSession) -> dict:
    """更新 `project profile` 相关数据。

    Args:
        project_id: str => 项目 ID。
        body: ResearchProjectProfileUpdateRequest => `body` 参数。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    _require_research_access(request, session.user_id)
    try:
        return request.app.state.research_project_profile_service.upsert(
            project_id, session.user_id,
            agent_instructions=body.agent_instructions,
            expected_revision=body.expected_revision,
        )
    except MemoryRevisionConflict as error:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "code": "revision_conflict", "current_revision": error.current_revision,
        }) from error
    except KeyError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "科研项目不存在") from error
    except ValueError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error


def _load_active_project(
    project_id: str,
    request: Request,
    user_id: str,
) -> dict:
    """加载 `active project` 相关数据。"""
    project_store: ResearchProjectStore = request.app.state.research_project_store
    project = project_store.get_project(project_id, user_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "科研项目不存在")
    if project["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "科研项目已归档")
    return project


@router.get("/projects/{project_id}/frontier-jobs")
def list_frontier_jobs(
    project_id: str,
    request: Request,
    session: CurrentSession,
) -> list[dict]:
    """列出 `frontier jobs` 相关数据。

    Args:
        project_id: str => 项目 ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        list[dict] => 处理结果。
    """
    _require_research_access(request, session.user_id)
    _load_active_project(project_id, request, session.user_id)
    store: FrontierTrackingStore = request.app.state.frontier_tracking_store
    return store.list_jobs(project_id, session.user_id)


@router.post(
    "/projects/{project_id}/frontier-jobs",
    status_code=status.HTTP_202_ACCEPTED,
)
def create_frontier_job(
    project_id: str,
    body: FrontierTrackingCreateRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    """创建 `frontier job` 相关数据。

    Args:
        project_id: str => 项目 ID。
        body: FrontierTrackingCreateRequest => `body` 参数。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    _require_research_access(request, session.user_id)
    _load_active_project(project_id, request, session.user_id)
    run = _workflow_facade(request).start_frontier_tracking(
        project_id=project_id,
        user_id=session.user_id,
        query=body.query.strip(),
        time_window_years=body.time_window_years,
        max_results=body.max_results,
    )
    return run.payload


@router.get("/frontier-jobs/{job_id}")
def get_frontier_job(
    job_id: str,
    request: Request,
    session: CurrentSession,
) -> dict:
    """获取 `frontier job` 相关数据。

    Args:
        job_id: str => job ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    _require_research_access(request, session.user_id)
    store: FrontierTrackingStore = request.app.state.frontier_tracking_store
    job = store.get_job(job_id, session.user_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "前沿追踪任务不存在")
    return job
