# backend/core/web/routers/preferences.py

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal
from backend.core.web.deps import get_current_session
from backend.core.web.schemas import (
    VALID_MAJORS,
    VALID_STYLES,
    VALID_TONES,
    UpdatePreferencesRequest,
    UpdateUserProfileRequest,
    UserPreferencesOut,
    UserProfileOut,
)

router = APIRouter(prefix="/me/preferences", tags=["preferences"])
profile_router = APIRouter(prefix="/me/profile", tags=["profile"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]

# 合法枚举值在 schemas.py 统一维护 与分组接口共用


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


@profile_router.get("")
def get_profile(
    request: Request,
    session: CurrentSession,
) -> UserProfileOut:
    """获取当前用户的学习档案(专业/年级/当前教学周/学期总周数)"""
    user_store: UserStore = request.app.state.user_store
    user = user_store.get_by_id(session.user_id)

    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    return UserProfileOut(
        major=user.major,
        grade=user.grade,
        current_week=user.current_week,
        total_weeks=user.total_weeks,
        profile_enabled=user.profile_enabled,
    )


@profile_router.patch("")
def update_profile(
    body: UpdateUserProfileRequest,
    request: Request,
    session: CurrentSession,
) -> UserProfileOut:
    """部分更新用户学习档案 只改传入的字段

    跨字段约束 current_week <= total_weeks 在此校验：
        - 同时传两者：直接校验
        - 只传其一：读当前用户记录补全另一边再校验
    """
    updates = body.model_dump(exclude_unset=True)
    user_store: UserStore = request.app.state.user_store

    # major 枚举校验
    if "major" in updates and updates["major"] not in VALID_MAJORS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"major 非法 合法值: {sorted(VALID_MAJORS)}",
        )

    # 跨字段约束 current_week <= total_weeks
    if "current_week" in updates or "total_weeks" in updates:
        user = user_store.get_by_id(session.user_id)
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
        cw = updates.get("current_week", user.current_week)
        tw = updates.get("total_weeks", user.total_weeks)
        if cw > tw:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"current_week({cw}) 不能大于 total_weeks({tw})",
            )

    if updates:
        updated = user_store.update_profile(
            user_id=session.user_id,
            major=updates.get("major"),
            grade=updates.get("grade"),
            current_week=updates.get("current_week"),
            total_weeks=updates.get("total_weeks"),
            profile_enabled=updates.get("profile_enabled"),
        )
        if not updated:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    # 返回最新值
    user = user_store.get_by_id(session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    return UserProfileOut(
        major=user.major,
        grade=user.grade,
        current_week=user.current_week,
        total_weeks=user.total_weeks,
        profile_enabled=user.profile_enabled,
    )
