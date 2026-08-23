"""Authenticated API for running code blocks in the Agent sandbox."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.core.utils.models import SessionPrincipal
from backend.core.web.deps import get_current_session
from backend.core.web.schemas import SandboxRunRequest
from backend.sandbox.sandbox import SandboxError, SandboxService

router = APIRouter(prefix="/sandbox", tags=["sandbox"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]


@router.post("/run", status_code=status.HTTP_200_OK)
async def run_code_block(
    body: SandboxRunRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    """Run a user-visible code block without exposing a shell command API."""

    conversation = request.app.state.chat_store.get_conversation(
        body.conversation_id, session.user_id
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对话不存在或无权访问")
    service = getattr(request.app.state, "sandbox_service", None)
    if not isinstance(service, SandboxService):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "沙箱服务尚未配置")
    try:
        return await service.execute_code(
            user_id=session.user_id,
            conversation_id=body.conversation_id,
            code=body.code,
            language=body.language,
            timeout_seconds=body.timeout_seconds,
        )
    except SandboxError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
