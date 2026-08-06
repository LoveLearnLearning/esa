# backend/core/web/routers/groups.py

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.core.stores.group_store import GroupStore
from backend.core.utils.models import SessionPrincipal
from backend.core.web.deps import get_current_session
from backend.core.web.routers._validators import validate_style_tone
from backend.core.web.schemas import GroupCreateRequest, GroupOut, GroupUpdateRequest

router = APIRouter(prefix="/groups", tags=["groups"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]
GROUP_LIMIT = 20


def _load_owned_group(
    request: Request,
    group_id: str,
    session: SessionPrincipal,
) -> dict:
    group_store: GroupStore = request.app.state.group_store
    group = group_store.get_group(group_id, user_id=session.user_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分组不存在")
    return group


@router.get("")
def list_groups(
    request: Request,
    session: CurrentSession,
) -> list[GroupOut]:
    group_store: GroupStore = request.app.state.group_store
    return [GroupOut(**group) for group in group_store.list_groups(session.user_id)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_group(
    body: GroupCreateRequest,
    request: Request,
    session: CurrentSession,
) -> GroupOut:
    validate_style_tone(body.style, body.tone)
    group_store: GroupStore = request.app.state.group_store
    group = group_store.create_group(
        user_id=session.user_id,
        name=body.name,
        description=body.description,
        custom_instruction=body.custom_instruction,
        style=body.style,
        tone=body.tone,
        group_limit=GROUP_LIMIT,
    )
    if group is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"分组数量已达上限({GROUP_LIMIT} 个)",
        )
    return GroupOut(**group, conversation_count=0)


@router.patch("/{group_id}")
def update_group(
    group_id: str,
    body: GroupUpdateRequest,
    request: Request,
    session: CurrentSession,
) -> GroupOut:
    _load_owned_group(request, group_id, session)
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "至少需要提供一个需要修改的字段",
        )

    for field in ("name", "description", "custom_instruction"):
        if updates.get(field) is None:
            updates.pop(field, None)

    # style/tone 显式传 null 表示恢复继承用户级设置，因此不能清除。
    if not updates:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "没有可更新的有效字段",
        )

    validate_style_tone(updates.get("style"), updates.get("tone"))
    group_store: GroupStore = request.app.state.group_store
    if updates and not group_store.update_group(
        group_id,
        user_id=session.user_id,
        **updates,
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分组不存在")

    updated = group_store.get_group(group_id, user_id=session.user_id)
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分组不存在")
    return GroupOut(**updated)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: str,
    request: Request,
    session: CurrentSession,
) -> None:
    group_store: GroupStore = request.app.state.group_store
    if not group_store.delete_group(group_id, session.user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分组不存在")
