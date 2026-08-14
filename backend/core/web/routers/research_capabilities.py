from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from backend.core.services.research_data_service import (
    MAX_DATASET_BYTES,
    ResearchDataService,
)
from backend.core.services.research_writing_service import ResearchWritingService
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

router = APIRouter(prefix="/research", tags=["research"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]


def _require_project(request: Request, user_id: str, project_id: str) -> dict:
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
    store: ResearchWritingStore = request.app.state.research_writing_store
    document = store.get_document(document_id, session.user_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "科研文档不存在")
    _require_project(request, session.user_id, document["project_id"])
    job = store.create_job(
        document_id=document_id,
        project_id=document["project_id"],
        user_id=session.user_id,
        operation=body.operation,
        instruction=body.instruction,
        source_text=body.source_text,
    )
    service: ResearchWritingService = request.app.state.research_writing_service
    service.submit(job["job_id"])
    return job


@router.get("/writing-jobs/{job_id}")
def get_writing_job(
    job_id: str,
    request: Request,
    session: CurrentSession,
) -> dict:
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
    store: ResearchDataStore = request.app.state.research_data_store
    dataset = store.get_dataset(dataset_id, session.user_id)
    if dataset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "科研数据集不存在")
    _require_project(request, session.user_id, dataset["project_id"])
    job = store.create_job(
        dataset_id=dataset_id,
        project_id=dataset["project_id"],
        user_id=session.user_id,
        analysis_type=body.analysis_type,
        parameters=body.parameters,
    )
    service: ResearchDataService = request.app.state.research_data_service
    service.submit(job["job_id"])
    return job


@router.get("/analysis-jobs/{job_id}")
def get_analysis_job(
    job_id: str,
    request: Request,
    session: CurrentSession,
) -> dict:
    store: ResearchDataStore = request.app.state.research_data_store
    job = store.get_job(job_id, session.user_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "数据分析任务不存在")
    return job
