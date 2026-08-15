# backend/core/router/models.py

"""Trusted routing contracts shared by the web and agent layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping, TypeAlias

WorkspaceType: TypeAlias = Literal["learning", "teaching", "research"]


def _frozen_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """处理 `_frozen_mapping` 相关逻辑。"""
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True, slots=True)
class TrustedIdentity:
    """Identity produced from an authenticated session and server-side user row."""

    user_id: str
    username: str
    account_role: str
    status: str = "active"

    def __post_init__(self) -> None:
        """完成实例初始化后的校验与派生字段构建。"""
        if not self.user_id or not self.username:
            raise ValueError("trusted identity requires user_id and username")
        if self.status != "active":
            raise ValueError("inactive identity cannot be routed")


@dataclass(frozen=True, slots=True)
class ResourceScope:
    """Already-authorized resources bound to the current conversation."""

    project_id: str | None = None
    class_id: str | None = None
    assignment_id: str | None = None
    attachment_ids: tuple[str, ...] = ()
    capabilities: frozenset[str] = frozenset()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """完成实例初始化后的校验与派生字段构建。"""
        object.__setattr__(self, "attachment_ids", tuple(dict.fromkeys(self.attachment_ids)))
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata))
        if self.assignment_id and not self.class_id:
            raise ValueError("assignment scope requires a class scope")

    @property
    def markers(self) -> tuple[str, ...]:
        """处理 `markers` 相关逻辑。"""
        values = [
            f"project:{self.project_id}" if self.project_id else "",
            f"class:{self.class_id}" if self.class_id else "",
            f"assignment:{self.assignment_id}" if self.assignment_id else "",
        ]
        values.extend(f"capability:{item}" for item in sorted(self.capabilities))
        return tuple(item for item in values if item)


@dataclass(frozen=True, slots=True)
class WorkspaceRoute:
    """Immutable result of identity, workspace, and resource authorization."""

    workspace_type: WorkspaceType
    agent_profile_id: str
    skill_scopes: frozenset[str]
    tool_scopes: frozenset[str]
    prompt_key: str
    profile_policy: str
    memory_policy_id: str
    resource_scope: ResourceScope
    action_policy: str

    def __post_init__(self) -> None:
        """完成实例初始化后的校验与派生字段构建。"""
        object.__setattr__(self, "skill_scopes", frozenset(self.skill_scopes))
        object.__setattr__(self, "tool_scopes", frozenset(self.tool_scopes))
        if self.workspace_type not in {"learning", "teaching", "research"}:
            raise ValueError(f"unsupported workspace: {self.workspace_type!r}")
        required_scope = self.workspace_type
        if required_scope not in self.skill_scopes or required_scope not in self.tool_scopes:
            raise ValueError("route must include its workspace capability scope")
