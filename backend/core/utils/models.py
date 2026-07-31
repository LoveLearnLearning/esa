# backend/core/utils/models.py

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar


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
    profile_enabled: bool = True


@dataclass
class SessionPrincipal:
    """
    生命周期内的对象
    """

    session_id: str
    user_id: str
    issued_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime = field(default_factory=datetime.now)
