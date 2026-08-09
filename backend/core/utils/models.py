# backend/core/utils/models.py

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from backend.agent.memories.memory_models import ProfileSnapshot


@dataclass
class ToolCall:
    name: str
    arguments: dict


@dataclass
class ParsedOutput:
    reasoning: str | None = None
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class AgentStreamEvent:
    event: str
    data: dict


@dataclass
class UserRecord:
    """用来存放用户数据。"""

    TOTAL_WEEKS_DEFAULT: ClassVar[int] = 18

    id: str
    username: str
    password_hash: str
    status: str

    preferred_style: str = "concise"
    preferred_tone: str = "friendly"
    custom_instruction: str = ""

    major: str = "cs"
    grade: str = ""
    current_week: int = 1
    total_weeks: int = TOTAL_WEEKS_DEFAULT
    profile_enabled: bool = True

    learning_profile_enabled: bool = True
    inferred_profile_enabled: bool = True


@dataclass
class MemorySettings:
    """记忆与画像开关设置，实际持久化在 memory_settings 表。"""

    user_id: str
    learning_profile_enabled: bool = True
    inferred_profile_enabled: bool = True
    default_conversation_mode: str = "normal"
    episodic_retention_days: int = 180
    created_at: str = ""
    updated_at: str = ""


@dataclass
class SessionPrincipal:
    """生命周期内的登录会话对象。"""

    session_id: str
    user_id: str
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PromptContext:
    """
    Prompt 构建上下文。

    风格/语调合并规则:
      group_style/group_tone 非 None 时覆盖 preferred_style/preferred_tone。

    指令合并顺序:
      系统 -> 用户级 -> 分组级 -> 系统生成的教学路由提示 -> 当前消息。

    pedagogy_context 与 autoload_skills_context 都是系统内部生成内容，
    不能由客户端直接控制。
    """

    preferred_style: str = "concise"
    preferred_tone: str = "friendly"
    custom_instruction: str = ""
    user_profile_context: "ProfileSnapshot | None" = (
        None  # 结构化画像快照 由 ProfileBuilder 生成
    )
    group_style: str | None = None
    group_tone: str | None = None
    group_custom_instruction: str = ""
    conversation_mode: str = "normal"

    # 由 Agent._prepare_run 内部生成，不属于用户可写偏好。
    pedagogy_context: str = ""
    autoload_skills_context: str = ""


@dataclass
class MessageContext:
    """发消息公共前置结果，含 Agent 调用所需上下文。"""

    user: UserRecord
    history: list[dict]
    user_profile_context: "ProfileSnapshot | None"
    group_style: str | None
    group_tone: str | None
    group_custom_instruction: str
    conversation_mode: str = "normal"
