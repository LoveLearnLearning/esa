# backend/core/utils/models.py

from dataclasses import dataclass, field
from datetime import datetime


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
class UserRecord:
    """
    用来存放用户数据
    """

    id: str
    username: str
    password_hash: str
    status: str


@dataclass
class SessionPrincipal:
    """
    生命周期内的对象
    """

    session_id: str
    user_id: str
    issued_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime = field(default_factory=datetime.now)
