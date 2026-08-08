"""CoreMemory -> ProfileStore 的受控结构化投影层。

设计原则：
- CoreMemory 仍然是按需 Tool 检索的数据源，不允许把所有长期记忆重新塞回 Prompt。
- 只有短小、稳定、明确属于个性化画像的 preference/profile 记忆才允许投影。
- 项目详情、一般事实、约束、学习过程等保持在 CoreMemory 中，继续按需读取。
- 显式设置字段（style/tone/major 等）绝不能被记忆投影覆盖。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.agent.memories.memory_models import ProfileOrigin

_SAFE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{1,63}$")

_RESERVED_FIELDS = {
    "preferred_style",
    "preferred_tone",
    "custom_instruction",
    "major",
    "grade",
    "current_week",
    "total_weeks",
    "profile_enabled",
}

_SENSITIVE_KEY_PARTS = {
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "private_key",
    "access_key",
}

_PROFILE_SAFE_PREFIXES = (
    "preferred_",
    "preference_",
    "learning_",
    "study_",
    "coding_",
    "communication_",
    "explanation_",
)

_PROFILE_SAFE_SUFFIXES = (
    "_preference",
    "_preferences",
)


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    projected: bool
    field_key: str | None = None
    reason: str = ""
    status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "projected": self.projected,
            "field_key": self.field_key,
            "reason": self.reason,
            "status": self.status,
        }


class ProfileProjection:
    """把少量安全的 CoreMemory 事实投影为结构化画像维度。"""

    MAX_PROJECTABLE_CONTENT_CHARS = 240

    def __init__(self, user_store, profile_store) -> None:
        self._user_store = user_store
        self._profile_store = profile_store

    @staticmethod
    def _is_sensitive_key(memory_key: str) -> bool:
        lowered = memory_key.lower()
        return any(part in lowered for part in _SENSITIVE_KEY_PARTS)

    @classmethod
    def _is_projectable(cls, memory_key: str, content: str, category: str) -> tuple[bool, str]:
        memory_key = memory_key.strip()
        content = content.strip()
        category = category.strip().lower()

        if category not in {"preference", "profile"}:
            return False, "category_not_profile_relevant"
        if not _SAFE_KEY_RE.fullmatch(memory_key):
            return False, "unsafe_or_unstructured_memory_key"
        if memory_key in _RESERVED_FIELDS:
            return False, "reserved_explicit_setting_field"
        if cls._is_sensitive_key(memory_key):
            return False, "sensitive_memory_key"
        if not content:
            return False, "empty_content"
        if len(content) > cls.MAX_PROJECTABLE_CONTENT_CHARS:
            return False, "content_too_long_for_profile_projection"

        # profile 比 preference 更宽泛，因此只允许明显与个性化/学习偏好相关的 key。
        if category == "profile":
            lowered = memory_key.lower()
            if not (
                lowered.startswith(_PROFILE_SAFE_PREFIXES)
                or lowered.endswith(_PROFILE_SAFE_SUFFIXES)
            ):
                return False, "profile_key_not_whitelisted"

        return True, ""

    def project_memory(self, user_name: str, memory: dict[str, Any]) -> ProjectionResult:
        """把一条已经持久化的 CoreMemory 投影到 ProfileStore；失败时不影响原记忆。"""
        user_name = user_name.strip()
        if not user_name:
            return ProjectionResult(False, reason="missing_user_name")

        user = self._user_store.get_by_username(user_name)
        if user is None:
            return ProjectionResult(False, reason="user_not_found")

        memory_key = str(memory.get("memory_key") or "").strip()
        content = str(memory.get("content") or "").strip()
        category = str(memory.get("category") or "general").strip().lower()

        allowed, reason = self._is_projectable(memory_key, content, category)
        if not allowed:
            return ProjectionResult(False, field_key=memory_key or None, reason=reason)

        memory_id = str(memory.get("id") or "").strip()
        source_ids = [memory_id] if memory_id else []

        # 用户手动 suppress 过的字段不能因为同名记忆再次保存而被静默激活。
        existing = self._profile_store.get_dimension(
            user.id,
            memory_key,
            include_expired=True,
        )
        status = "suppressed" if existing and existing.get("status") == "suppressed" else "active"

        # 显式设置属于更高优先级来源，绝不由记忆覆盖。
        if existing and existing.get("origin") == ProfileOrigin.EXPLICIT_SETTING.value:
            return ProjectionResult(
                False,
                field_key=memory_key,
                reason="existing_explicit_setting_has_higher_priority",
                status=existing.get("status"),
            )

        saved = self._profile_store.upsert_dimension(
            user_id=user.id,
            field_key=memory_key,
            value=content,
            origin=ProfileOrigin.EXPLICIT_MEMORY.value,
            confidence=0.95,
            source_memory_ids=source_ids,
            status=status,
        )
        return ProjectionResult(
            projected=bool(saved),
            field_key=memory_key,
            reason="" if saved else "profile_store_write_failed",
            status=status,
        )

    def remove_memory_projection(
        self,
        user_name: str,
        memory: dict[str, Any],
    ) -> ProjectionResult:
        """仅删除由该 CoreMemory 自身产生的投影，避免误删其他画像来源。"""
        user = self._user_store.get_by_username(user_name.strip())
        if user is None:
            return ProjectionResult(False, reason="user_not_found")

        field_key = str(memory.get("memory_key") or "").strip()
        memory_id = str(memory.get("id") or "").strip()
        if not field_key:
            return ProjectionResult(False, reason="missing_memory_key")

        existing = self._profile_store.get_dimension(
            user.id,
            field_key,
            include_expired=True,
        )
        if existing is None:
            return ProjectionResult(False, field_key=field_key, reason="projection_not_found")
        if existing.get("origin") != ProfileOrigin.EXPLICIT_MEMORY.value:
            return ProjectionResult(False, field_key=field_key, reason="projection_owned_by_other_origin")

        source_ids = {str(item) for item in (existing.get("source_memory_ids") or [])}
        if memory_id and memory_id not in source_ids:
            return ProjectionResult(False, field_key=field_key, reason="projection_owned_by_other_memory")

        deleted = self._profile_store.delete_dimension(
            user.id,
            field_key,
            actor="agent",
        )
        return ProjectionResult(
            projected=False,
            field_key=field_key,
            reason="projection_removed" if deleted else "projection_delete_failed",
        )
