"""Canonical immutable definitions for every supported workspace type."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from backend.agent.workspaces.models import LoopPolicy, WorkspaceRuntimeProfile
from backend.core.utils.config import AGENT_LOOP_TIME, AGENT_TOOL_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class WorkspaceDefinition:
    workspace_type: str
    definition_version: int
    allowed_roles: frozenset[str]
    display_name: str
    description: str
    manifest_capabilities: tuple[str, ...]
    profile_id: str
    prompt_key: str
    skill_scopes: frozenset[str]
    tool_scopes: frozenset[str]
    context_policy: frozenset[str]
    profile_policy: str
    memory_policy_id: str
    action_policy: str
    loop_policy: LoopPolicy
    required_resource_capabilities: frozenset[str] = frozenset()
    optional_resource_capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.definition_version < 1:
            raise ValueError("workspace definition version must be positive")
        if not self.allowed_roles:
            raise ValueError("workspace definition requires an allowed role")
        if self.workspace_type not in self.skill_scopes:
            raise ValueError("workspace definition lacks its skill scope")
        if self.workspace_type not in self.tool_scopes:
            raise ValueError("workspace definition lacks its tool scope")
        if self.required_resource_capabilities & self.optional_resource_capabilities:
            raise ValueError("required and optional resource capabilities overlap")

    @property
    def runtime_profile(self) -> WorkspaceRuntimeProfile:
        return WorkspaceRuntimeProfile(
            profile_id=self.profile_id,
            workspace_type=self.workspace_type,
            prompt_key=self.prompt_key,
            skill_scopes=self.skill_scopes,
            tool_scopes=self.tool_scopes,
            context_policy=self.context_policy,
            profile_policy=self.profile_policy,
            memory_policy_id=self.memory_policy_id,
            action_policy=self.action_policy,
            loop_policy=self.loop_policy,
            version=self.definition_version,
        )

    def to_manifest_payload(self) -> dict[str, object]:
        return {
            "type": self.workspace_type,
            "name": self.display_name,
            "description": self.description,
            "capabilities": list(self.manifest_capabilities),
        }


_LOOP_POLICY = LoopPolicy(
    max_iterations=AGENT_LOOP_TIME,
    tool_timeout_seconds=AGENT_TOOL_TIMEOUT_SECONDS,
)

_DEFINITIONS = (
    WorkspaceDefinition(
        workspace_type="learning",
        definition_version=1,
        allowed_roles=frozenset({"student"}),
        display_name="\u5b66\u4e60\u7a7a\u95f4",
        description="\u8bfe\u7a0b\u5b66\u4e60\u3001\u7ec3\u4e60\u3001\u8bfe\u8868\u4e0e\u77e5\u8bc6\u638c\u63e1",
        manifest_capabilities=("chat", "schedule", "knowledge_map", "mastery"),
        profile_id="learning.default.v1",
        prompt_key="learning.v1",
        skill_scopes=frozenset({"common", "learning"}),
        tool_scopes=frozenset({"common", "learning"}),
        context_policy=frozenset(
            {"style", "profile", "group", "summary", "attachments", "strategy"}
        ),
        profile_policy="learning.v1",
        memory_policy_id="learning.v1",
        action_policy="learning.v1",
        loop_policy=_LOOP_POLICY,
        optional_resource_capabilities=frozenset(
            {
                "attachments",
                "classroom",
                "assignment",
                "own_assignments",
                "own_submissions",
                "published_feedback",
            }
        ),
    ),
    WorkspaceDefinition(
        workspace_type="teaching",
        definition_version=1,
        allowed_roles=frozenset({"teacher"}),
        display_name="\u6559\u5b66\u7a7a\u95f4",
        description="\u6559\u5b66\u8bbe\u8ba1\u4e0e\u6559\u5e08\u5de5\u4f5c\u6d41",
        manifest_capabilities=("chat", "teaching_context"),
        profile_id="teaching.default.v1",
        prompt_key="teaching.v1",
        skill_scopes=frozenset({"common", "teaching"}),
        tool_scopes=frozenset({"common", "teaching"}),
        context_policy=frozenset(
            {"style", "profile", "group", "summary", "attachments", "resource"}
        ),
        profile_policy="teaching.v1",
        memory_policy_id="teaching.v1",
        action_policy="teaching.v1",
        loop_policy=_LOOP_POLICY,
        optional_resource_capabilities=frozenset(
            {
                "attachments",
                "classroom",
                "assignment",
                "classroom_management",
            }
        ),
    ),
    WorkspaceDefinition(
        workspace_type="research",
        definition_version=1,
        allowed_roles=frozenset({"student", "teacher"}),
        display_name="\u79d1\u7814\u7a7a\u95f4",
        description="\u79d1\u7814\u9879\u76ee\u3001\u6587\u732e\u3001\u5199\u4f5c\u3001\u8d8b\u52bf\u4e0e\u6570\u636e\u5206\u6790",
        manifest_capabilities=("chat", "research_projects", "attachments"),
        profile_id="research.default.v1",
        prompt_key="research.v1",
        skill_scopes=frozenset({"common", "research"}),
        tool_scopes=frozenset({"common", "research"}),
        context_policy=frozenset(
            {
                "style",
                "profile",
                "group",
                "summary",
                "attachments",
                "workspace_profile",
                "resource",
            }
        ),
        profile_policy="research.v1",
        memory_policy_id="research.v1",
        action_policy="research.v1",
        loop_policy=_LOOP_POLICY,
        optional_resource_capabilities=frozenset(
            {"attachments", "research_project"}
        ),
    ),
)

WORKSPACE_DEFINITIONS: Mapping[str, WorkspaceDefinition] = MappingProxyType(
    {item.workspace_type: item for item in _DEFINITIONS}
)


def get_workspace_definition(workspace_type: str) -> WorkspaceDefinition:
    try:
        return WORKSPACE_DEFINITIONS[workspace_type]
    except KeyError as error:
        raise KeyError(f"unsupported workspace: {workspace_type!r}") from error
