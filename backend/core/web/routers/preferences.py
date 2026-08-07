# backend/core/web/routers/preferences.py

import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.agent.memories.memory_models import ProfileQuery
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal
from backend.core.web.deps import get_current_session
from backend.core.web.rate_limit import profile_limiter
from backend.core.web.schemas import (
    VALID_MAJORS,
    VALID_STYLES,
    VALID_TONES,
    MemorySettingsOut,
    ProfileFieldOut,
    ProfileSourcesOut,
    ProfileViewOut,
    UpdateMemorySettingsRequest,
    UpdatePreferencesRequest,
    UpdateProfileExplicitRequest,
    UpdateUserProfileRequest,
    UserPreferencesOut,
    UserProfileOut,
)

router = APIRouter(prefix="/me/preferences", tags=["preferences"])
profile_router = APIRouter(prefix="/me/profile", tags=["profile"])
memory_settings_router = APIRouter(prefix="/me/memory-settings", tags=["memory-settings"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]

# 合法枚举值在 schemas.py 统一维护 与分组接口共用
# 合法会话模式 枚举
VALID_CONVERSATION_MODES = {"normal", "no_write", "isolated"}


def _snapshot_to_view(snap_dict: dict) -> ProfileViewOut:
    """将 ProfileSnapshot.to_dict() 结果映射为 ProfileViewOut

    各分节 list[dict] 逐项转为 ProfileFieldOut 仅保留 field/value/origin/confidence 四字段
    其余 source_memory_ids/last_confirmed_at 等内部字段不输出到视图。
    """
    def to_fields(items: list[dict]) -> list[ProfileFieldOut]:
        return [
            ProfileFieldOut(
                field=item["field"],
                value=item["value"],
                origin=item["origin"],
                confidence=item["confidence"],
            )
            for item in items
        ]

    return ProfileViewOut(
        explicit=to_fields(snap_dict.get("explicit_context", [])),
        preferences=to_fields(snap_dict.get("response_preferences", [])),
        goals=to_fields(snap_dict.get("active_goals", [])),
        projects=to_fields(snap_dict.get("active_projects", [])),
        learning_state=to_fields(snap_dict.get("relevant_learning_state", [])),
        inferred_patterns=to_fields(snap_dict.get("inferred_patterns", [])),
        profile_version=snap_dict.get("profile_version", 0),
        generated_at=snap_dict.get("generated_at", ""),
    )


def _build_profile_view(request: Request, session: SessionPrincipal) -> ProfileViewOut:
    """构建完整画像视图 供 GET /me/profile 与 PATCH /me/profile/explicit 复用

    仅查看无聊天上下文 current_message 留空 group 级覆盖均为 None。
    """
    user_store: UserStore = request.app.state.user_store
    user = user_store.get_by_id(session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    profile_builder = request.app.state.profile_builder
    query = ProfileQuery(
        user_id=session.user_id,
        username=user.username,
        current_message="",  # 仅查看无聊天上下文
    )
    snapshot = profile_builder.build(query)
    return _snapshot_to_view(snapshot.to_dict())


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
) -> ProfileViewOut:
    """获取当前用户的完整画像视图(Profile V2)

    通过 ProfileBuilder 构建快照 显式字段 + 偏好 + 推断模式等一并返回。
    旧版仅返回 major/grade/week 的字段 现可通过 PATCH /me/profile/explicit 写回。
    """
    return _build_profile_view(request, session)


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


@profile_router.patch("/explicit")
@profile_limiter.limit("10/minute")
def update_profile_explicit(
    body: UpdateProfileExplicitRequest,
    request: Request,
    session: CurrentSession,
) -> ProfileViewOut:
    """更新显式画像字段(Profile V2) 只改传入字段

    覆盖学习档案(major/grade/current_week/total_weeks)与输出偏好(style/tone/custom_instruction)
    校验：major/style/tone 枚举 current_week <= total_weeks。
    写入后重新构建完整画像视图返回。
    """
    updates = body.model_dump(exclude_unset=True)
    user_store: UserStore = request.app.state.user_store

    # major 枚举校验
    if "major" in updates and updates["major"] not in VALID_MAJORS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"major 非法 合法值: {sorted(VALID_MAJORS)}",
        )
    # style 枚举校验
    if "preferred_style" in updates and updates["preferred_style"] not in VALID_STYLES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"preferred_style 非法 合法值: {sorted(VALID_STYLES)}",
        )
    # tone 枚举校验
    if "preferred_tone" in updates and updates["preferred_tone"] not in VALID_TONES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"preferred_tone 非法 合法值: {sorted(VALID_TONES)}",
        )
    # custom_instruction 截断到 500 字符 兜底
    if "custom_instruction" in updates and len(updates["custom_instruction"]) > 500:
        updates["custom_instruction"] = updates["custom_instruction"][:500]

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

    # 输出偏好相关字段 走 update_preferences
    pref_keys = {"preferred_style", "preferred_tone", "custom_instruction"}
    if pref_keys & updates.keys():
        updated = user_store.update_preferences(
            user_id=session.user_id,
            preferred_style=updates.get("preferred_style"),
            preferred_tone=updates.get("preferred_tone"),
            custom_instruction=updates.get("custom_instruction"),
        )
        if not updated:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    # 学习档案相关字段 走 update_profile(profile_enabled 不在此端点暴露 传 None)
    profile_keys = {"major", "grade", "current_week", "total_weeks"}
    if profile_keys & updates.keys():
        updated = user_store.update_profile(
            user_id=session.user_id,
            major=updates.get("major"),
            grade=updates.get("grade"),
            current_week=updates.get("current_week"),
            total_weeks=updates.get("total_weeks"),
            profile_enabled=None,
        )
        if not updated:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    # 显式字段变更后失效画像缓存
    if updates:
        request.app.state.profile_builder.invalidate(session.user_id)

    # 返回最新完整画像视图
    return _build_profile_view(request, session)


@profile_router.get("/sources")
def get_profile_sources(
    request: Request,
    session: CurrentSession,
    field_key: str = "",
) -> ProfileSourcesOut:
    """解释指定画像字段的来源(origin/置信度/支撑记忆/确认时间)

    field_key 为空或未命中时返回 found=False 的默认项。
    source_memory_ids 在 DB 中以 JSON 字符串存储 这里解析为 list。
    """
    profile_store = request.app.state.profile_store
    dim = profile_store.get_dimension(session.user_id, field_key)

    if dim is None:
        return ProfileSourcesOut(
            field_key=field_key,
            found=False,
            origin="default",
            confidence=0.0,
        )

    # store 已将 source_memory_ids_json 解析为 list 这里做兼容：字符串再 parse 一次
    raw_ids = dim.get("source_memory_ids", [])
    if isinstance(raw_ids, str):
        try:
            source_memory_ids = json.loads(raw_ids)
        except (json.JSONDecodeError, TypeError):
            source_memory_ids = []
    else:
        source_memory_ids = raw_ids

    last_confirmed_at = dim.get("last_confirmed_at")
    return ProfileSourcesOut(
        field_key=dim.get("field_key", field_key),
        origin=dim.get("origin", "default"),
        confidence=dim.get("confidence", 0.0),
        source_memory_ids=source_memory_ids,
        last_confirmed_at=last_confirmed_at,
        found=True,
    )


@profile_router.delete("/inferred/{field_key}")
@profile_limiter.limit("10/minute")
def delete_inferred_field(
    field_key: str,
    request: Request,
    session: CurrentSession,
) -> dict:
    """抑制(suppress)指定的推断画像字段

    将维度置为 suppressed 状态 不物理删除 便于审计与恢复。
    记录不存在时返回 404。
    抑制后立即失效 ProfileBuilder 缓存 确保下一轮不注入已删除字段。
    """
    profile_store = request.app.state.profile_store
    suppressed = profile_store.suppress_dimension(session.user_id, field_key)
    if not suppressed:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"画像字段 {field_key} 不存在或已被抑制",
        )
    # 失效 ProfileBuilder 缓存 保证下一轮 build 不返回已抑制字段
    request.app.state.profile_builder.invalidate(session.user_id)
    return {"deleted": True, "field_key": field_key}


# ===== 数据导出与被遗忘权 (P2-16) =====


@profile_router.get("/export")
def export_profile(
    request: Request,
    session: CurrentSession,
) -> dict:
    """导出当前用户的全部画像数据 (GDPR 数据导出)

    返回 user_profile_dimensions 表中该用户的全部记录 包括 active 和 suppressed。
    """
    profile_store = request.app.state.profile_store
    dimensions = profile_store.export_all_dimensions(session.user_id)
    return {
        "user_id": session.user_id,
        "exported_at": datetime.now().isoformat(),
        "dimensions": dimensions,
    }


@profile_router.delete("")
@profile_limiter.limit("1/minute")
def delete_all_profile(
    request: Request,
    session: CurrentSession,
    confirm: str = "",
) -> dict:
    """删除当前用户的全部画像数据 (被遗忘权)

    物理删除 user_profile_dimensions 中该用户的所有记录。
    需要传入 confirm=DELETE 查询参数作为二次确认 防止误操作。

    注意: 不删除 memory_settings 表记录 (由 UserStore 独立管理)。
    """
    if confirm != "DELETE":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "需要传入 confirm=DELETE 查询参数作为二次确认",
        )

    profile_store = request.app.state.profile_store
    deleted_count = profile_store.delete_all_dimensions(session.user_id)

    # 失效画像缓存
    request.app.state.profile_builder.invalidate(session.user_id)

    return {
        "deleted": True,
        "deleted_count": deleted_count,
        "message": f"已删除 {deleted_count} 条画像维度记录",
    }


# ===== 记忆与画像开关 =====


@memory_settings_router.get("")
def get_memory_settings(
    request: Request,
    session: CurrentSession,
) -> MemorySettingsOut:
    """获取当前用户的记忆与画像开关 未配置时返回默认值"""
    user_store: UserStore = request.app.state.user_store
    settings = user_store.get_memory_settings(session.user_id)

    if settings is None:
        return MemorySettingsOut(
            learning_profile_enabled=True,
            inferred_profile_enabled=True,
            default_conversation_mode="normal",
        )

    return MemorySettingsOut(
        learning_profile_enabled=settings.learning_profile_enabled,
        inferred_profile_enabled=settings.inferred_profile_enabled,
        default_conversation_mode=settings.default_conversation_mode,
    )


@memory_settings_router.patch("")
@profile_limiter.limit("10/minute")
def update_memory_settings(
    body: UpdateMemorySettingsRequest,
    request: Request,
    session: CurrentSession,
) -> MemorySettingsOut:
    """部分更新记忆与画像开关 只改传入字段

    校验 default_conversation_mode ∈ {normal, no_write, isolated}。
    """
    updates = body.model_dump(exclude_unset=True)
    user_store: UserStore = request.app.state.user_store

    if (
        "default_conversation_mode" in updates
        and updates["default_conversation_mode"] not in VALID_CONVERSATION_MODES
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"default_conversation_mode 非法 合法值: {sorted(VALID_CONVERSATION_MODES)}",
        )

    if updates:
        updated = user_store.update_memory_settings(
            user_id=session.user_id,
            learning_profile_enabled=updates.get("learning_profile_enabled"),
            inferred_profile_enabled=updates.get("inferred_profile_enabled"),
            default_conversation_mode=updates.get("default_conversation_mode"),
        )
        if not updated:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
        # 开关变更后失效画像缓存
        request.app.state.profile_builder.invalidate(session.user_id)

    # 返回最新值 未配置时落默认
    settings = user_store.get_memory_settings(session.user_id)
    if settings is None:
        return MemorySettingsOut(
            learning_profile_enabled=True,
            inferred_profile_enabled=True,
            default_conversation_mode="normal",
        )

    return MemorySettingsOut(
        learning_profile_enabled=settings.learning_profile_enabled,
        inferred_profile_enabled=settings.inferred_profile_enabled,
        default_conversation_mode=settings.default_conversation_mode,
    )
