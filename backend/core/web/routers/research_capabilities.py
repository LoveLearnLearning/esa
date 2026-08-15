# backend/core/web/routers/research_capabilities.py

"""提供 `research_capabilities` 相关功能。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from backend.core.services.research_data_service import (
    MAX_DATASET_BYTES,
    ResearchDataService,
)
from backend.core.stores.research_data_store import ResearchDataStore
from backend.core.stores.research_project_store import ResearchProjectStore
from backend.core.stores.research_writing_store import ResearchWritingStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal
from backend.core.web.deps import get_current_session
from backend.core.web.schemas import (
    ResearchAnalysisJobCreateRequest,
    ResearchDocumentCreateRequest,
    ResearchDocumentUpdateRequest,
    ResearchWritingJobCreateRequest,
)
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
        frontier_store=getattr(request.app.state, "frontier_tracking_store", None),
        frontier_service=getattr(request.app.state, "frontier_tracking_service", None),
        writing_store=request.app.state.research_writing_store,
        writing_service=request.app.state.research_writing_service,
        data_store=request.app.state.research_data_store,
        data_service=request.app.state.research_data_service,
    )


def _require_project(request: Request, user_id: str, project_id: str) -> dict:
    """处理 `_require_project` 相关逻辑。"""
    user_store: UserStore = request.app.state.user_store
    user = user_store.get_by_id(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    if not WorkspaceAccessPolicy.can_access(user.account_role, "research"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权进入科研空间")
    project_store: ResearchProjectStore = request.app.state.research_project_store
    project = project_store.get_project(project_id, user_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "科研项目不存在")
    if project["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "科研项目已归档")
    return project


@router.get("/projects/{project_id}/documents")
def list_documents(
    project_id: str,
    request: Request,
    session: CurrentSession,
) -> list[dict]:
    """列出 `documents` 相关数据。

    Args:
        project_id: str => 项目 ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        list[dict] => 处理结果。
    """
    _require_project(request, session.user_id, project_id)
    store: ResearchWritingStore = request.app.state.research_writing_store
    return store.list_documents(project_id, session.user_id)


@router.post("/projects/{project_id}/documents", status_code=status.HTTP_201_CREATED)
def create_document(
    project_id: str,
    body: ResearchDocumentCreateRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    """创建 `document` 相关数据。

    Args:
        project_id: str => 项目 ID。
        body: ResearchDocumentCreateRequest => `body` 参数。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    _require_project(request, session.user_id, project_id)
    store: ResearchWritingStore = request.app.state.research_writing_store
    return store.create_document(
        project_id=project_id,
        user_id=session.user_id,
        title=body.title.strip(),
        document_type=body.document_type,
        content=body.content,
    )


@router.get("/documents/{document_id}")
def get_document(
    document_id: str,
    request: Request,
    session: CurrentSession,
) -> dict:
    """获取 `document` 相关数据。

    Args:
        document_id: str => document ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    store: ResearchWritingStore = request.app.state.research_writing_store
    document = store.get_document(document_id, session.user_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "科研文档不存在")
    return document


@router.patch("/documents/{document_id}")
def update_document(
    document_id: str,
    body: ResearchDocumentUpdateRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    """更新 `document` 相关数据。

    Args:
        document_id: str => document ID。
        body: ResearchDocumentUpdateRequest => `body` 参数。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    store: ResearchWritingStore = request.app.state.research_writing_store
    document = store.update_document(
        document_id,
        session.user_id,
        title=body.title.strip() if body.title is not None else None,
        content=body.content,
    )
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "科研文档不存在")
    return document


@router.get("/documents/{document_id}/versions")
def list_document_versions(
    document_id: str,
    request: Request,
    session: CurrentSession,
) -> list[dict]:
    """列出 `document versions` 相关数据。

    Args:
        document_id: str => document ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        list[dict] => 处理结果。
    """
    store: ResearchWritingStore = request.app.state.research_writing_store
    if store.get_document(document_id, session.user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "科研文档不存在")
    return store.list_versions(document_id, session.user_id)


@router.post(
    "/documents/{document_id}/writing-jobs",
    status_code=status.HTTP_202_ACCEPTED,
)
def create_writing_job(
    document_id: str,
    body: ResearchWritingJobCreateRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    """创建 `writing job` 相关数据。

    Args:
        document_id: str => document ID。
        body: ResearchWritingJobCreateRequest => `body` 参数。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    store: ResearchWritingStore = request.app.state.research_writing_store
    document = store.get_document(document_id, session.user_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "科研文档不存在")
    _require_project(request, session.user_id, document["project_id"])
    run = _workflow_facade(request).start_research_writing(
        document_id=document_id,
        user_id=session.user_id,
        operation=body.operation,
        instruction=body.instruction,
        source_text=body.source_text,
    )
    return run.payload


@router.get("/writing-jobs/{job_id}")
def get_writing_job(
    job_id: str,
    request: Request,
    session: CurrentSession,
) -> dict:
    """获取 `writing job` 相关数据。

    Args:
        job_id: str => job ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    store: ResearchWritingStore = request.app.state.research_writing_store
    job = store.get_job(job_id, session.user_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "写作任务不存在")
    return job


@router.get("/projects/{project_id}/datasets")
def list_datasets(
    project_id: str,
    request: Request,
    session: CurrentSession,
) -> list[dict]:
    """列出 `datasets` 相关数据。

    Args:
        project_id: str => 项目 ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        list[dict] => 处理结果。
    """
    _require_project(request, session.user_id, project_id)
    store: ResearchDataStore = request.app.state.research_data_store
    return store.list_datasets(project_id, session.user_id)


@router.post("/projects/{project_id}/datasets", status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    project_id: str,
    request: Request,
    session: CurrentSession,
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form(min_length=1, max_length=120)],
) -> dict:
    """处理 `upload_dataset` 相关逻辑。

    Args:
        project_id: str => 项目 ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。
        file: Annotated[UploadFile, File()] => `file` 参数。
        name: Annotated[str, Form(min_length=1, max_length=120)] => `name` 参数。

    Returns:
        dict => 处理结果。
    """
    _require_project(request, session.user_id, project_id)
    content = await file.read(MAX_DATASET_BYTES + 1)
    service: ResearchDataService = request.app.state.research_data_service
    try:
        return service.ingest(
            project_id=project_id,
            user_id=session.user_id,
            name=name.strip(),
            filename=file.filename or "dataset.csv",
            media_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except (ValueError, UnicodeDecodeError, OSError) as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error


@router.get("/datasets/{dataset_id}")
def get_dataset(
    dataset_id: str,
    request: Request,
    session: CurrentSession,
) -> dict:
    """获取 `dataset` 相关数据。

    Args:
        dataset_id: str => dataset ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    store: ResearchDataStore = request.app.state.research_data_store
    dataset = store.get_dataset(dataset_id, session.user_id)
    if dataset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "科研数据集不存在")
    return dataset


@router.get("/datasets/{dataset_id}/analysis-jobs")
def list_analysis_jobs(
    dataset_id: str,
    request: Request,
    session: CurrentSession,
) -> list[dict]:
    """列出 `analysis jobs` 相关数据。

    Args:
        dataset_id: str => dataset ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        list[dict] => 处理结果。
    """
    store: ResearchDataStore = request.app.state.research_data_store
    if store.get_dataset(dataset_id, session.user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "科研数据集不存在")
    return store.list_jobs(dataset_id, session.user_id)


@router.post(
    "/datasets/{dataset_id}/analysis-jobs",
    status_code=status.HTTP_202_ACCEPTED,
)
def create_analysis_job(
    dataset_id: str,
    body: ResearchAnalysisJobCreateRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    """创建 `analysis job` 相关数据。

    Args:
        dataset_id: str => dataset ID。
        body: ResearchAnalysisJobCreateRequest => `body` 参数。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    store: ResearchDataStore = request.app.state.research_data_store
    dataset = store.get_dataset(dataset_id, session.user_id)
    if dataset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "科研数据集不存在")
    _require_project(request, session.user_id, dataset["project_id"])
    run = _workflow_facade(request).start_dataset_analysis(
        dataset_id=dataset_id,
        user_id=session.user_id,
        analysis_type=body.analysis_type,
        parameters=body.parameters,
    )
    return run.payload


@router.get("/analysis-jobs/{job_id}")
def get_analysis_job(
    job_id: str,
    request: Request,
    session: CurrentSession,
) -> dict:
    """获取 `analysis job` 相关数据。

    Args:
        job_id: str => job ID。
        request: Request => 当前 HTTP 请求。
        session: CurrentSession => `session` 参数。

    Returns:
        dict => 处理结果。
    """
    store: ResearchDataStore = request.app.state.research_data_store
    job = store.get_job(job_id, session.user_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "数据分析任务不存在")
    return job
