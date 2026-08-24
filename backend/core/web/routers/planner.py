"""Authenticated planner API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from backend.core.stores.planner_store import PlannerStore
from backend.core.utils.models import SessionPrincipal
from backend.core.web.deps import get_current_session
from backend.core.web.schemas import (
    PlannerGoalCreateRequest,
    PlannerGoalOut,
    PlannerGoalUpdateRequest,
    PlannerSnapshotOut,
    PlannerTodoCreateRequest,
    PlannerTodoOut,
    PlannerTodoUpdateRequest,
)


router = APIRouter(prefix="/me/planner", tags=["planner"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]


def _store(request: Request) -> PlannerStore:
    return request.app.state.planner_store


@router.get("")
def get_planner(request: Request, session: CurrentSession) -> PlannerSnapshotOut:
    store = _store(request)
    return PlannerSnapshotOut(
        todos=[PlannerTodoOut(**item) for item in store.list_todos(session.user_id)],
        goals=[PlannerGoalOut(**item) for item in store.list_goals(session.user_id)],
    )


@router.post("/todos", status_code=status.HTTP_201_CREATED)
def create_todo(
    body: PlannerTodoCreateRequest, request: Request, session: CurrentSession
) -> PlannerTodoOut:
    return PlannerTodoOut(
        **_store(request).create_todo(
            session.user_id,
            body.title.strip(),
            due_at=body.due_at.isoformat() if body.due_at else None,
        )
    )


@router.patch("/todos/{todo_id}")
def update_todo(
    todo_id: str,
    body: PlannerTodoUpdateRequest,
    request: Request,
    session: CurrentSession,
) -> PlannerTodoOut:
    store = _store(request)
    updates = body.model_dump(exclude_unset=True)
    if "due_at" in updates:
        updates["due_at"] = updates["due_at"].isoformat() if updates["due_at"] else None
    if not store.update_todo(todo_id, session.user_id, **updates):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "待办不存在")
    item = store.get_todo(todo_id, session.user_id)
    if item is None:  # pragma: no cover - update and read use the same owned row
        raise HTTPException(status.HTTP_404_NOT_FOUND, "待办不存在")
    return PlannerTodoOut(**item)


@router.delete("/todos/{todo_id}", status_code=204, response_class=Response)
def delete_todo(todo_id: str, request: Request, session: CurrentSession) -> None:
    if not _store(request).delete_todo(todo_id, session.user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "待办不存在")


@router.post("/goals", status_code=status.HTTP_201_CREATED)
def create_goal(
    body: PlannerGoalCreateRequest, request: Request, session: CurrentSession
) -> PlannerGoalOut:
    return PlannerGoalOut(
        **_store(request).create_goal(
            session.user_id,
            body.title.strip(),
            description=body.description.strip(),
            target_at=body.target_at.isoformat() if body.target_at else None,
            progress=body.progress,
        )
    )


@router.patch("/goals/{goal_id}")
def update_goal(
    goal_id: str,
    body: PlannerGoalUpdateRequest,
    request: Request,
    session: CurrentSession,
) -> PlannerGoalOut:
    store = _store(request)
    updates = body.model_dump(exclude_unset=True)
    if "target_at" in updates:
        updates["target_at"] = (
            updates["target_at"].isoformat() if updates["target_at"] else None
        )
    if not store.update_goal(goal_id, session.user_id, **updates):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "目标不存在")
    item = store.get_goal(goal_id, session.user_id)
    if item is None:  # pragma: no cover - update and read use the same owned row
        raise HTTPException(status.HTTP_404_NOT_FOUND, "目标不存在")
    return PlannerGoalOut(**item)


@router.delete("/goals/{goal_id}", status_code=204, response_class=Response)
def delete_goal(goal_id: str, request: Request, session: CurrentSession) -> None:
    if not _store(request).delete_goal(goal_id, session.user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "目标不存在")
