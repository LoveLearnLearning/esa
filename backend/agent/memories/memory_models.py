# backend/agent/memories/memory_models.py

"""
结构化用户画像系统的纯数据模型。

本文件只定义画像字段、单轮画像快照、画像构建入参等数据结构 不含任何数据库或存储逻辑。
ProfileBuilder 等组件基于这些模型组装每轮注入 Prompt 的画像内容。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ProfileOrigin(str, Enum):
    """画像字段值的来源标识 用于追溯可信度与覆盖优先级。"""

    # 用户在设置页显式配置 优先级最高
    EXPLICIT_SETTING = "explicit_setting"
    # 用户显式告诉 Agent 要记住的内容
    EXPLICIT_MEMORY = "explicit_memory"
    # 推断记忆后被用户确认
    CONFIRMED_MEMORY = "confirmed_memory"
    # 由掌握度/练习数据计算得出
    DERIVED_LEARNING_STATE = "derived_learning_state"
    # 由对话模式推断而来
    INFERRED_PATTERN = "inferred_pattern"
    # 系统默认值 优先级最低
    DEFAULT = "default"


@dataclass
class ProfileField:
    """
    单个画像维度 附带来源与置信度跟踪。

    field        => 字段键 例如 "preferred_code_language" / "major" / "mastery_level"
    value        => 字段值 可为 str/int/float/dict/list
    origin       => 该值的来源
    confidence   => 置信度 0.0~1.0
    source_memory_ids => 支撑该字段的记忆项 ID 列表
    last_confirmed_at => 用户最近一次确认该字段的时间
    """

    field: str
    value: object
    origin: ProfileOrigin
    confidence: float = 1.0
    source_memory_ids: list[str] = field(default_factory=list)
    last_confirmed_at: datetime | None = None

    def to_dict(self) -> dict:
        """序列化为普通 dict datetime 转为 ISO 字符串 ProfileOrigin 转为其字符串值。"""
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
    """
    单轮结构化画像结果 由 ProfileBuilder 每轮重新构建。

    explicit_context        => 来自 UserRecord 的显式上下文 major/grade/current_week/total_weeks
    response_preferences    => 风格/语气/自定义指令 已应用群组覆盖
    active_goals            => 当前学习目标 MVP 阶段为空
    active_projects         => 当前进行的项目 MVP 阶段为空
    relevant_learning_state => 与当前问题相关知识点掌握度
    relevant_constraints    => 环境/约束 MVP 阶段为空
    inferred_patterns       => 由 CoreMemory 推断的模式
    source_memory_ids       => 本快照引用到的全部记忆 ID
    generated_at            => 快照生成时间
    """

    user_id: str
    profile_version: int
    explicit_context: list[ProfileField] = field(default_factory=list)
    response_preferences: list[ProfileField] = field(default_factory=list)
    active_goals: list[ProfileField] = field(default_factory=list)
    active_projects: list[ProfileField] = field(default_factory=list)
    relevant_learning_state: list[ProfileField] = field(default_factory=list)
    relevant_constraints: list[ProfileField] = field(default_factory=list)
    inferred_patterns: list[ProfileField] = field(default_factory=list)
    source_memory_ids: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """序列化完整快照为普通 dict 各 ProfileField 调用其 to_dict datetime 转 ISO 字符串。"""
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
        """
        返回适合注入 Prompt 的 JSON 字符串。

        仅包含非空分节 且每项只保留 field/value/origin/confidence 四个字段
        source_memory_ids 与 last_confirmed_at 属内部字段 不输出到 Prompt。

        当序列化结果超过 max_tokens 时按优先级截断:
        explicit_context -> response_preferences -> relevant_learning_state -> inferred_patterns
        低优先级分节优先被整段丢弃 同一分节内截断时保留置信度更高的字段。
        token 数采用 len(json_str) // 3 的近似估算 适配中英混合内容。
        """
        # 按优先级从高到低排列 优先级低的分节在预算不足时优先被丢弃
        sections: list[tuple[str, list[ProfileField]]] = [
            ("explicit_context", self.explicit_context),
            ("response_preferences", self.response_preferences),
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

        def estimate_tokens(payload: dict) -> int:
            return len(json.dumps(payload, ensure_ascii=False, indent=2)) // 3

        payload: dict[str, list[dict]] = {}

        for name, items in sections:
            if not items:
                continue
            # 同一分节内按置信度降序 stable sort 保留同置信度字段的原始顺序
            # 截断时置信度高的字段排在前面从而被优先保留
            ordered = sorted(items, key=lambda f: f.confidence, reverse=True)
            serialized = [field_to_dict(item) for item in ordered]

            # 整段放入若不超预算 直接采用并继续尝试下一分节
            candidate = {**payload, name: serialized}
            if estimate_tokens(candidate) <= max_tokens:
                payload = candidate
                continue

            # 整段超预算 在分节内逐项放入 保留置信度高的字段
            truncated: list[dict] = []
            for item_dict in serialized:
                trial = {**payload, name: truncated + [item_dict]}
                if estimate_tokens(trial) <= max_tokens:
                    truncated.append(item_dict)
                else:
                    break
            if truncated:
                payload[name] = truncated
            # 预算已耗尽 低优先级分节不再放入
            break

        return json.dumps(payload, ensure_ascii=False, indent=2)


@dataclass
class ProfileQuery:
    """
    ProfileBuilder.build() 的入参。

    user_id              => 用户唯一标识
    username             => 用户名 MasteryStore/CoreMemory 仍以 username 为键 这是 user_id 迁移完成前的过渡桥接
    conversation_id      => 当前会话 ID
    group_id             => 所属群组 ID 用于应用群组级风格/语气/指令覆盖
    current_message      => 用户本轮问题
    recent_messages      => 最近的对话消息
    group_style          => 群组级风格覆盖
    group_tone           => 群组级语气覆盖
    group_custom_instruction => 群组级自定义指令覆盖
    """

    user_id: str
    username: str
    conversation_id: str | None = None
    group_id: str | None = None
    current_message: str = ""
    recent_messages: list[dict] = field(default_factory=list)
    group_style: str | None = None
    group_tone: str | None = None
    group_custom_instruction: str = ""
