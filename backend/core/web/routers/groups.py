# backend/core/web/routers/groups.py

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.core.stores.group_store import GroupStore
from backend.core.utils.models import SessionPrincipal
from backend.core.web.deps import get_current_session
from backend.core.web.routers._validators import validate_style_tone
from backend.core.web.schemas import (
    GroupCreateRequest,
    GroupOut,
    GroupUpdateRequest,
)

router = APIRouter(prefix="/groups", tags=["groups"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]

# 每用户分组上限
GROUP_LIMIT = 20


def _load_owned_group(
    request: Request,
    group_id: str,
    session: SessionPrincipal,
) -> dict:
    """辅助函数：取出分组 并校验归属
    不存在或不属于当前用户的分组返回 404

    Args:
        request: Request            => 请求对象
        group_id: str               => 分组 id
        session: SessionPrincipal   => 用户登陆信息

    Returns:
        dict                        => 分组信息
    """
    group_store: GroupStore = request.app.state.group_store
    group: dict | None = group_store.get_group(group_id)
    if group is None or group["user_id"] != session.user_id:
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
    group_store: GroupStore = request.app.state.group_store

    validate_style_tone(body.style, body.tone)

    # 上限校验放在 GroupStore 事务内 与插入同锁 防止并发突破上限
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

    group["conversation_count"] = 0

    return GroupOut(**group)


@router.patch("/{group_id}")
def update_group(
    group_id: str,
    body: GroupUpdateRequest,
    request: Request,
    session: CurrentSession,
) -> GroupOut:
    _load_owned_group(request, group_id, session)
    group_store: GroupStore = request.app.state.group_store

    updates = body.model_dump(exclude_unset=True)
    # name/description/custom_instruction 是 NOT NULL 列 显式传 null 视为未提供 删除避免写入 NULL 触发 500
    # style/tone 的 None 不删除 保留传入 store 表示"改回继承用户级"(SET style = NULL)
    for field in ("name", "description", "custom_instruction"):
        if field in updates and updates[field] is None:
            del updates[field]
    validate_style_tone(updates.get("style"), updates.get("tone"))

    if updates:
        group_store.update_group(group_id, **updates)

    # 返回最新分组信息
    updated = group_store.get_group(group_id)
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分组不存在")

    return GroupOut(**updated)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: str,
    request: Request,
    session: CurrentSession,
) -> None:
    _load_owned_group(request, group_id, session)
    group_store: GroupStore = request.app.state.group_store
    group_store.delete_group(group_id, session.user_id)
