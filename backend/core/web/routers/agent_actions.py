"""User approval API for high-impact Agent Actions."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.core.utils.models import SessionPrincipal
from backend.core.web.deps import get_current_session

router = APIRouter(prefix="/me/agent-actions", tags=["agent-actions"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]
AgentActionStatus = Literal[
    "pending",
    "approved",
    "executing",
    "succeeded",
    "failed",
    "rejected",
    "expired",
]


@router.get("")
def list_actions(
    request: Request,
    session: CurrentSession,
    status: AgentActionStatus | None = None,
) -> list[dict]:
    return request.app.state.agent_action_store.list(session.user_id, status)


@router.get("/{action_id}")
def get_action(action_id: str, request: Request, session: CurrentSession) -> dict:
    item = request.app.state.agent_action_store.get(action_id, session.user_id)
    if item is None:
        raise HTTPException(404, "动作请求不存在")
    return item


def _decision(
    request: Request,
    session: SessionPrincipal,
    action_id: str,
    decision: Literal["approve", "reject"],
) -> dict:
    service = request.app.state.agent_action_service
    try:
        if decision == "approve":
            return service.approve_and_execute(action_id, session.user_id)
        return service.reject(action_id, session.user_id)
    except KeyError as error:
        raise HTTPException(404, "动作请求不存在") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post("/{action_id}/approve")
def approve_action(
    action_id: str, request: Request, session: CurrentSession
) -> dict:
    return _decision(request, session, action_id, "approve")


@router.post("/{action_id}/reject")
def reject_action(
    action_id: str, request: Request, session: CurrentSession
) -> dict:
    return _decision(request, session, action_id, "reject")
