# backend/agent/memories/memory_models.py

"""结构化用户画像系统的数据模型。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime
from enum import Enum
class ProfileOrigin(str, Enum):
    """封装 `ProfileOrigin` 的状态与行为。"""
    EXPLICIT_SETTING = "explicit_setting"
    EXPLICIT_MEMORY = "explicit_memory"
    CONFIRMED_MEMORY = "confirmed_memory"
    DERIVED_LEARNING_STATE = "derived_learning_state"
    INFERRED_PATTERN = "inferred_pattern"
    DEFAULT = "default"


@dataclass
class ProfileField:
    """封装 `ProfileField` 的状态与行为。"""
    field: str
    value: object
    origin: ProfileOrigin
    confidence: float = 1.0
    source_memory_ids: list[str] = dataclass_field(default_factory=list)
    last_confirmed_at: datetime | None = None

    def to_dict(self) -> dict:
        """将当前对象转换为字典。"""
        return {
            "field": self.field,
            "value": self.value,
            "origin": self.origin.value,
            "confidence": self.confidence,
            "source_memory_ids": list(self.source_memory_ids),
            "last_confirmed_at": (
                self.last_confirmed_at.isoformat()
                if self.last_confirmed_at is not None
                else None
            ),
        }


@dataclass
class ProfileSnapshot:
    """单轮结构化画像快照。

    response_preferences 仍保留给 API/UI 展示，但不再由 to_prompt_json() 重复注入。
    style/tone/custom_instruction 的 Prompt 权威来源是 build_prompt.py。
    """

    user_id: str
    profile_version: int
    explicit_context: list[ProfileField] = dataclass_field(default_factory=list)
    response_preferences: list[ProfileField] = dataclass_field(default_factory=list)
    active_goals: list[ProfileField] = dataclass_field(default_factory=list)
    active_projects: list[ProfileField] = dataclass_field(default_factory=list)
    relevant_learning_state: list[ProfileField] = dataclass_field(default_factory=list)
    relevant_constraints: list[ProfileField] = dataclass_field(default_factory=list)
    inferred_patterns: list[ProfileField] = dataclass_field(default_factory=list)
    source_memory_ids: list[str] = dataclass_field(default_factory=list)
    generated_at: datetime = dataclass_field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """将当前对象转换为字典。"""
        return {
            "user_id": self.user_id,
            "profile_version": self.profile_version,
            "explicit_context": [item.to_dict() for item in self.explicit_context],
            "response_preferences": [
                item.to_dict() for item in self.response_preferences
            ],
            "active_goals": [item.to_dict() for item in self.active_goals],
            "active_projects": [item.to_dict() for item in self.active_projects],
            "relevant_learning_state": [
                item.to_dict() for item in self.relevant_learning_state
            ],
            "relevant_constraints": [
                item.to_dict() for item in self.relevant_constraints
            ],
            "inferred_patterns": [item.to_dict() for item in self.inferred_patterns],
            "source_memory_ids": list(self.source_memory_ids),
            "generated_at": self.generated_at.isoformat(),
        }

    def to_prompt_json(
        self,
        *,
        current_message: str = "",
        task_mode: str | None = None,
        resolved_kp_ids: tuple[str, ...] = (),
    ) -> str:
        """Project only task-relevant fields into compact, always-valid JSON."""

        planning = task_mode == "study_plan" or any(
            marker in current_message
            for marker in ("学习计划", "复习计划", "进度", "第几周", "考试时间")
        )
        resolved = set(resolved_kp_ids)

        def compact_learning_value(value: object) -> object:
            if not isinstance(value, dict):
                return value
            if resolved and value.get("kp_id") not in resolved:
                return None
            mastery = value.get("mastery")
            evidence = value.get("evidence")
            result = {
                key: value[key]
                for key in ("kp_id", "name", "course")
                if value.get(key) is not None
            }
            if isinstance(mastery, dict):
                result["mastery"] = {
                    key: mastery[key]
                    for key in (
                        "has_record",
                        "level",
                        "status",
                        "retention",
                        "needs_review",
                        "practice_count",
                    )
                    if mastery.get(key) is not None
                }
            if isinstance(evidence, dict):
                compact_evidence = {
                    key: evidence[key]
                    for key in ("count", "correct_rate", "independent_rate")
                    if evidence.get(key) is not None
                }
                misconceptions = evidence.get("recent_misconceptions")
                if isinstance(misconceptions, list) and misconceptions:
                    compact_evidence["recent_misconceptions"] = misconceptions[:2]
                if compact_evidence:
                    result["evidence"] = compact_evidence
            weak = value.get("weak_prerequisites")
            if isinstance(weak, list) and weak:
                result["weak_prerequisites"] = weak[:3]
            return result

        candidates: list[tuple[str, dict]] = []
        for item in sorted(
            self.relevant_learning_state,
            key=lambda field: field.confidence,
            reverse=True,
        ):
            value = compact_learning_value(item.value)
            if value is not None:
                candidates.append(
                    ("learning", {"field": item.field, "value": value})
                )

        for item in self.explicit_context:
            if item.field in {"current_week", "total_weeks"} and not planning:
                continue
            if item.field not in {"major", "grade", "current_week", "total_weeks"}:
                continue
            if item.value not in (None, ""):
                candidates.append(
                    ("context", {"field": item.field, "value": item.value})
                )

        for section_name, items in (
            ("goals", self.active_goals),
            ("constraints", self.relevant_constraints),
            (
                "patterns",
                sorted(
                    self.inferred_patterns,
                    key=lambda field: field.confidence,
                    reverse=True,
                )[:3],
            ),
        ):
            for item in sorted(items, key=lambda field: field.confidence, reverse=True):
                if item.value in (None, ""):
                    continue
                candidates.append(
                    (
                        section_name,
                        {
                            "field": item.field,
                            "value": item.value,
                            "confidence": round(item.confidence, 2),
                        },
                    )
                )

        payload: dict[str, list[dict]] = {}
        for section_name, candidate in candidates:
            payload.setdefault(section_name, []).append(candidate)

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


@dataclass
class ProfileQuery:
    """封装 `ProfileQuery` 的状态与行为。"""
    user_id: str
    username: str
    conversation_id: str | None = None
    group_id: str | None = None
    current_message: str = ""
    recent_messages: list[dict] = dataclass_field(default_factory=list)
    resolved_kp_ids: list[str] = dataclass_field(default_factory=list)
    group_style: str | None = None
    group_tone: str | None = None
    group_custom_instruction: str = ""
