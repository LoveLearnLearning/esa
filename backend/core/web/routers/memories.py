"""CoreMemory V2 management API and global-only legacy compatibility API."""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from backend.agent.memories.core_memory_models import MemoryRevisionConflict
from backend.agent.tools.context import AgentRuntimeDependencies, ToolExecutionContext
from backend.core.router import (
    ConversationContext,
    RoutingContext,
    resolve_identity,
    route_workspace,
)
from backend.core.router.errors import WorkspaceRoutingError
from backend.core.utils.models import SessionPrincipal
from backend.core.web.deps import get_current_session
from backend.core.web.schemas import (
    CoreMemoryCreateRequest,
    CoreMemoryRestoreRequest,
    CoreMemoryUpdateRequest,
    CoreMemoryUpsertRequest,
    MemoryCandidateDecisionRequest,
)

router = APIRouter(tags=["memories"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]


def _service(request: Request):
    service = getattr(request.app.state, "core_memory_service", None)
    if service is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "记忆服务尚未初始化")
    return service


def _context(
    request: Request,
    session: SessionPrincipal,
    workspace_type: str | None = None,
) -> ToolExecutionContext:
    user = request.app.state.user_store.get_by_id(session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    selected_workspace = workspace_type or (
        "teaching" if user.account_role == "teacher" else "learning"
    )
    identity = resolve_identity(session, user)
    route = route_workspace(
        identity,
        RoutingContext(
            ConversationContext(
                "memory-management",
                session.user_id,
                selected_workspace,
            )
        ),
    )
    return ToolExecutionContext(
        user_id=session.user_id,
        conversation_id="memory-management",
        workspace_route=route,
        authorized_resources=route.resource_scope,
        conversation_mode="normal",
        runtime_dependencies=AgentRuntimeDependencies(
            user_store=request.app.state.user_store,
            core_memory_service=_service(request),
        ),
        request_id=uuid4().hex,
        username=user.username,
    )


def _translate(error: Exception) -> HTTPException:
    if isinstance(error, MemoryRevisionConflict):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "revision_conflict",
                "current_revision": error.current_revision,
            },
        )
    if isinstance(error, KeyError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "记忆不存在")
    if isinstance(error, PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(error))
    if isinstance(error, WorkspaceRoutingError):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(error))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(error))


def _record_context(
    request: Request,
    session: SessionPrincipal,
    memory_id: str,
) -> ToolExecutionContext:
    record = _service(request).store.get(memory_id, session.user_id)
    if record is None:
        raise KeyError(memory_id)
    return _context(request, session, record.scope.workspace_type)


@router.get("/me/core-memories")
def list_core_memories(
    request: Request, session: CurrentSession, limit: int = 100, offset: int = 0
) -> list[dict]:
    return _service(request).list_all(session.user_id, limit=limit, offset=offset)


@router.post("/me/core-memories", status_code=status.HTTP_201_CREATED)
def create_core_memory(
    body: CoreMemoryCreateRequest, request: Request, session: CurrentSession
) -> dict:
    try:
        return (
            _service(request)
            .create_for_user(
                _context(request, session, body.workspace_type),
                memory_key=body.memory_key,
                content=body.content,
                category=body.category,
                scope_type=body.scope_type,
            )
            .to_dict()
        )
    except Exception as error:
        raise _translate(error) from error


@router.patch("/me/core-memories/{memory_id}")
def update_core_memory(
    memory_id: str,
    body: CoreMemoryUpdateRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    try:
        return (
            _service(request)
            .update(
                _record_context(request, session, memory_id),
                memory_id,
                expected_revision=body.expected_revision,
                content=body.content,
                category=body.category,
            )
            .to_dict()
        )
    except Exception as error:
        raise _translate(error) from error


@router.delete(
    "/me/core-memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def forget_core_memory(
    memory_id: str, request: Request, session: CurrentSession
) -> None:
    try:
        if not _service(request).forget(
            _record_context(request, session, memory_id), memory_id
        ):
            raise KeyError(memory_id)
    except Exception as error:
        raise _translate(error) from error


@router.post("/me/core-memories/{memory_id}/suppress")
def suppress_core_memory(
    memory_id: str, request: Request, session: CurrentSession
) -> dict:
    try:
        return (
            _service(request)
            .suppress(_record_context(request, session, memory_id), memory_id, True)
            .to_dict()
        )
    except Exception as error:
        raise _translate(error) from error


@router.post("/me/core-memories/{memory_id}/restore")
def unsuppress_core_memory(
    memory_id: str, request: Request, session: CurrentSession
) -> dict:
    try:
        return (
            _service(request)
            .suppress(_record_context(request, session, memory_id), memory_id, False)
            .to_dict()
        )
    except Exception as error:
        raise _translate(error) from error


@router.get("/me/core-memories/{memory_id}/versions")
def list_versions(
    memory_id: str, request: Request, session: CurrentSession
) -> list[dict]:
    try:
        return _service(request).versions(session.user_id, memory_id)
    except Exception as error:
        raise _translate(error) from error


@router.post("/me/core-memories/{memory_id}/versions/{revision}/restore")
def restore_version(
    memory_id: str,
    revision: int,
    body: CoreMemoryRestoreRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    try:
        return (
            _service(request)
            .restore_version(
                _record_context(request, session, memory_id),
                memory_id,
                revision,
                body.expected_revision,
            )
            .to_dict()
        )
    except Exception as error:
        raise _translate(error) from error


@router.get("/me/memory-candidates")
def list_candidates(request: Request, session: CurrentSession) -> list[dict]:
    return _service(request).list_candidates(session.user_id)


@router.post("/me/memory-candidates/{candidate_id}/accept")
def accept_candidate(
    candidate_id: str,
    body: MemoryCandidateDecisionRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    try:
        service = _service(request)
        candidate = service.store.get_candidate(candidate_id, session.user_id)
        if candidate is None:
            raise KeyError(candidate_id)
        workspace_type = body.workspace_type or candidate.scope.workspace_type
        return service.accept_candidate(
            _context(request, session, workspace_type),
            candidate_id,
            content=body.content,
            category=body.category,
            scope_type=body.scope_type,
        ).to_dict()
    except Exception as error:
        raise _translate(error) from error


@router.post(
    "/me/memory-candidates/{candidate_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def reject_candidate(
    candidate_id: str, request: Request, session: CurrentSession
) -> None:
    if not _service(request).reject_candidate(
        session.user_id,
        candidate_id,
        request_id=uuid4().hex,
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "候选记忆不存在")


@router.get("/me/memories")
def list_memories(request: Request, session: CurrentSession) -> list[dict]:
    return [
        {
            "memory_key": item["memory_key"],
            "content": item["content"],
            "category": item["category"],
        }
        for item in _service(request).list_all(session.user_id)
        if item["scope_type"] == "global" and item["status"] == "active"
    ]


@router.put("/me/memories", status_code=status.HTTP_201_CREATED)
def upsert_memory(
    body: CoreMemoryUpsertRequest, request: Request, session: CurrentSession
) -> dict:
    context, service = _context(request, session), _service(request)
    scope = service.policy.resolve_scope(context, "global")
    existing = service.store.get_by_key(
        session.user_id, body.memory_key.strip().casefold(), scope
    )
    try:
        record = (
            service.create_for_user(
                context,
                memory_key=body.memory_key,
                content=body.content,
                category=body.category,
                scope_type="global",
            )
            if existing is None
            else service.update(
                context,
                existing.memory_id,
                expected_revision=existing.revision,
                content=body.content,
                category=body.category,
            )
        )
        return {
            "memory_key": record.memory_key,
            "content": record.content,
            "category": record.category,
        }
    except Exception as error:
        raise _translate(error) from error


@router.delete(
    "/me/memories/{memory_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_memory(memory_key: str, request: Request, session: CurrentSession) -> None:
    context, service = _context(request, session), _service(request)
    existing = service.store.get_by_key(
        session.user_id,
        memory_key.strip().casefold(),
        service.policy.resolve_scope(context, "global"),
    )
    if existing is None or not service.forget(context, existing.memory_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "记忆不存在")
