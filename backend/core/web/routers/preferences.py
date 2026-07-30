# backend/core/web/routers/preferences.py

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal
from backend.core.web.deps import get_current_session
from backend.core.web.schemas import UpdatePreferencesRequest, UserPreferencesOut

router = APIRouter(prefix="/me/preferences", tags=["preferences"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]

# 合法枚举值 非法值返回 400
VALID_STYLES = {"concise", "detailed", "socratic"}
VALID_TONES = {"friendly", "formal", "encouraging", "strict"}


@router.get("")
def get_preferences(
    request: Request,
    session: CurrentSession,
) -> UserPreferencesOut:
    """获取当前用户的输出偏好(风格/语调/自定义指令)"""
    user_store: UserStore = request.app.state.user_store
    user = user_store.get_by_id(session.user_id)

    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    return UserPreferencesOut(
        preferred_style=user.preferred_style,
        preferred_tone=user.preferred_tone,
        custom_instruction=user.custom_instruction,
    )


@router.patch("")
def update_preferences(
    body: UpdatePreferencesRequest,
    request: Request,
    session: CurrentSession,
) -> UserPreferencesOut:
    """部分更新用户输出偏好 只改传入的字段"""
    # exclude_unset=True 只取用户实际传了的字段 None 的不算
    updates = body.model_dump(exclude_unset=True)

    # 枚举校验
    if "preferred_style" in updates and updates["preferred_style"] not in VALID_STYLES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"preferred_style 非法 合法值: {sorted(VALID_STYLES)}",
        )
    if "preferred_tone" in updates and updates["preferred_tone"] not in VALID_TONES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"preferred_tone 非法 合法值: {sorted(VALID_TONES)}",
        )

    # custom_instruction 截断到 500 字符 防御 pydantic 已校验 这里再兜一层
    if "custom_instruction" in updates and len(updates["custom_instruction"]) > 500:
        updates["custom_instruction"] = updates["custom_instruction"][:500]

    user_store: UserStore = request.app.state.user_store

    if updates:
        updated = user_store.update_preferences(
            user_id=session.user_id,
            preferred_style=updates.get("preferred_style"),
            preferred_tone=updates.get("preferred_tone"),
            custom_instruction=updates.get("custom_instruction"),
        )
        if not updated:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    # 返回最新值
    user = user_store.get_by_id(session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    return UserPreferencesOut(
        preferred_style=user.preferred_style,
        preferred_tone=user.preferred_tone,
        custom_instruction=user.custom_instruction,
    )
