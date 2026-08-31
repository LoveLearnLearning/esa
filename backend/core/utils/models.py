# backend/core/utils/models.py

"""定义数据模型与序列化结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from backend.agent.memories.memory_models import ProfileSnapshot


@dataclass
class ToolCall:
    """封装 `ToolCall` 的状态与行为。"""

    name: str
    arguments: dict


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    """Separate model, display, and audit projections of one tool result."""

    model_content: Any
    display_content: Any
    audit_metadata: Any | None = None

    def __getitem__(self, key: str) -> Any:
        """Keep mapping-style reads compatible for structured model payloads."""

        if not isinstance(self.model_content, dict):
            raise TypeError("model_content is not a mapping")
        return self.model_content[key]

    def get(self, key: str, default: Any = None) -> Any:
        """Return one model-content field for legacy direct executor callers."""

        if not isinstance(self.model_content, dict):
            return default
        return self.model_content.get(key, default)


@dataclass
class ParsedOutput:
    """表示 `parsed output` 数据结构。"""

    reasoning: str | None = None
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class AgentStreamEvent:
    """封装 `AgentStreamEvent` 的状态与行为。"""

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
    account_role: str = "student"
    display_name: str = ""

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

    # 邮箱身份：新用户注册时必填并已验证；老用户为 None 直至主动绑定
    email: str | None = None
    email_verified_at: str | None = None


@dataclass
class MemorySettings:
    """记忆与画像开关设置，实际持久化在 memory_settings 表。"""

    user_id: str
    saved_memory_enabled: bool = True
    chat_history_enabled: bool = True
    auto_extract_enabled: bool = False
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
    conversation_summary: str = ""
    conversation_mode: str = "normal"
    attachment_context: str = ""
    workspace_type: str = "learning"

    # 兼容 prompt builder 使用；生产 Agent 主链由 Workspace Runtime 生成。
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
    conversation_summary: str = ""
    conversation_mode: str = "normal"
    workspace_type: str = "learning"
    user_message_id: int | None = None
    resolved_kp_ids: tuple[str, ...] = ()
    pending_practice_kp_id: str | None = None
    knowledge_sources: tuple[str, ...] = ("personal", "public")
    personal_knowledge_base_id: str | None = None
