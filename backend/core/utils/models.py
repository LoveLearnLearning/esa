# backend/core/utils/models.py

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
    """
    用来存放用户数据
    """

    # 系统默认学期总周数（18 周）
    TOTAL_WEEKS_DEFAULT: ClassVar[int] = 18

    id: str
    username: str
    password_hash: str
    status: str

    # 用户偏好设置
    preferred_style: str = "concise"
    preferred_tone: str = "friendly"
    custom_instruction: str = ""

    # 学习档案设置（spec Task 4）
    # major: 专业 当前仅支持 "cs"（计算机学科）
    # grade: 年级 自由字符串 如 "大二" / "2023级"
    # current_week: 当前教学周 1-based
    # total_weeks: 学期总周数 影响 recommend_practice 优先级计算
    # profile_enabled: 用户画像开关 关闭时 Agent 不注入学情档案 + 不加载 profile_personalization skill
    major: str = "cs"
    grade: str = ""
    current_week: int = 1
    total_weeks: int = TOTAL_WEEKS_DEFAULT
    profile_enabled: bool = True  # deprecated: 已迁移到 memory_settings 表 由 learning_profile_enabled + inferred_profile_enabled 替代

    # 画像细粒度开关 (迁移自 profile_enabled 实际存储在 memory_settings 表)
    learning_profile_enabled: bool = True
    inferred_profile_enabled: bool = True


@dataclass
class MemorySettings:
    """记忆与画像开关设置 实际持久化在 memory_settings 表"""

    user_id: str
    learning_profile_enabled: bool = True
    inferred_profile_enabled: bool = True
    default_conversation_mode: str = "normal"  # normal / no_write / isolated
    episodic_retention_days: int = 180
    created_at: datetime = ""
    updated_at: datetime = ""


@dataclass
class SessionPrincipal:
    """
    生命周期内的对象
    """

    session_id: str
    user_id: str
    issued_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime = field(default_factory=datetime.now)


@dataclass
class PromptContext:
    """
    Prompt 构建上下文 收敛 agent 与 build_system_prompt 的 prompt 相关参数

    风格/语调合并规则: group_style/group_tone 非 None 时覆盖 preferred_style/preferred_tone
    指令合并顺序: 系统 -> 用户级(custom_instruction) -> 分组级(group_custom_instruction) -> 当前消息
    """

    preferred_style: str = "concise"
    preferred_tone: str = "friendly"
    custom_instruction: str = ""
    user_profile_context: "ProfileSnapshot | None" = None  # 结构化画像快照 由 ProfileBuilder 生成
    group_style: str | None = None
    group_tone: str | None = None
    group_custom_instruction: str = ""
    # 会话记忆模式: normal(读取并写入) / no_write(只读不写) / isolated(不读不写)
    conversation_mode: str = "normal"


@dataclass
class MessageContext:
    """
    发消息公共前置结果 含 agent 调用所需的全部上下文

    由 chat._prepare_message 构建供 send_message / stream_message 共用
    消除两个端点前 35 行重复代码
    """

    user: UserRecord
    history: list[dict]
    user_profile_context: "ProfileSnapshot | None"
    group_style: str | None
    group_tone: str | None
    group_custom_instruction: str
    # 会话记忆模式 由 _prepare_message 从 memory_settings 读取
    conversation_mode: str = "normal"
