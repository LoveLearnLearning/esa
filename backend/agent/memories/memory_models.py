"""结构化用户画像系统的数据模型。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime
from enum import Enum
from typing import Protocol


class _TokenEncoding(Protocol):
    def encode(self, text: str) -> list[int]: ...


_TIKTOKEN_ENCODING: _TokenEncoding | None

try:  # pragma: no cover - 可选依赖
    from tiktoken import get_encoding as _get_encoding

    _TIKTOKEN_ENCODING = _get_encoding("cl100k_base")
except Exception:  # noqa: BLE001
    _TIKTOKEN_ENCODING = None


def _estimate_tokens(text: str) -> int:
    if _TIKTOKEN_ENCODING is not None:
        return len(_TIKTOKEN_ENCODING.encode(text))

    cjk = 0
    ascii_count = 0
    other = 0
    for ch in text:
        code = ord(ch)
        if code <= 0x007F:
            ascii_count += 1
        elif 0x4E00 <= code <= 0x9FFF:
            cjk += 1
        else:
            other += 1
    return int(ascii_count / 4 + cjk * 1.5 + other)


class ProfileOrigin(str, Enum):
    EXPLICIT_SETTING = "explicit_setting"
    EXPLICIT_MEMORY = "explicit_memory"
    CONFIRMED_MEMORY = "confirmed_memory"
    DERIVED_LEARNING_STATE = "derived_learning_state"
    INFERRED_PATTERN = "inferred_pattern"
    DEFAULT = "default"


@dataclass
class ProfileField:
    field: str
    value: object
    origin: ProfileOrigin
    confidence: float = 1.0
    source_memory_ids: list[str] = dataclass_field(default_factory=list)
    last_confirmed_at: datetime | None = None

    def to_dict(self) -> dict:
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

    def to_prompt_json(self, max_tokens: int = 700) -> str:
        """序列化真正需要进入模型上下文的画像数据，并按优先级控制预算。

        注意：response_preferences 不在此处输出，避免与 build_prompt.py 中已经解析好的
        style/tone/custom_instruction 双重注入。
        """
        sections: list[tuple[str, list[ProfileField]]] = [
            ("explicit_context", self.explicit_context),
            ("active_goals", self.active_goals),
            ("active_projects", self.active_projects),
            ("relevant_constraints", self.relevant_constraints),
            ("relevant_learning_state", self.relevant_learning_state),
            ("inferred_patterns", self.inferred_patterns),
        ]

        def field_to_dict(item: ProfileField) -> dict:
            return {
                "field": item.field,
                "value": item.value,
                "origin": item.origin.value,
                "confidence": item.confidence,
            }

        def token_count(payload: dict) -> int:
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            return _estimate_tokens(text)

        payload: dict[str, list[dict]] = {}
        for section_name, items in sections:
            if not items:
                continue

            ordered = sorted(items, key=lambda item: item.confidence, reverse=True)
            serialized = [field_to_dict(item) for item in ordered]
            candidate = {**payload, section_name: serialized}
            if token_count(candidate) <= max_tokens:
                payload = candidate
                continue

            truncated: list[dict] = []
            for item_dict in serialized:
                trial = {**payload, section_name: truncated + [item_dict]}
                if token_count(trial) <= max_tokens:
                    truncated.append(item_dict)
                else:
                    break
            if truncated:
                payload[section_name] = truncated
            break

        return json.dumps(payload, ensure_ascii=False, indent=2)


@dataclass
class ProfileQuery:
    user_id: str
    username: str
    conversation_id: str | None = None
    group_id: str | None = None
    current_message: str = ""
    recent_messages: list[dict] = dataclass_field(default_factory=list)
    group_style: str | None = None
    group_tone: str | None = None
    group_custom_instruction: str = ""
