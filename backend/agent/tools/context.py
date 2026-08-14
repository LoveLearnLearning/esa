"""Trusted per-turn context and application dependency container for tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from backend.agent.workspaces.routing import ResourceScope, WorkspaceRoute


class TeachingContextReader(Protocol):
    def read_teaching_context(
        self,
        *,
        user_id: str,
        class_id: str | None,
        assignment_id: str | None,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class AgentRuntimeDependencies:
    user_store: Any | None = None
    profile_store: Any | None = None
    chat_store: Any | None = None
    teaching_store: Any | None = None
    teaching_context_reader: TeachingContextReader | None = None
    research_project_store: Any | None = None
    research_project_profile_service: Any | None = None
    agent_action_service: Any | None = None
    core_memory_service: Any | None = None
    frontier_tracking_service: Any | None = None
    research_writing_service: Any | None = None
    research_data_service: Any | None = None
    attachment_store: Any | None = None
    multimodal_sessions: Any | None = None
    knowledge_graph_store: Any | None = None
    mastery_store: Any | None = None
    learning_evidence_store: Any | None = None
    learning_state_service: Any | None = None
    rag_service: Any | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra)))


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    user_id: str
    conversation_id: str
    workspace_route: WorkspaceRoute
    authorized_resources: ResourceScope
    conversation_mode: str
    runtime_dependencies: AgentRuntimeDependencies
    request_id: str
    run_id: str = ""
    username: str = ""
    total_weeks: int | None = None

    def __post_init__(self) -> None:
        if (
            not self.user_id
            or not self.conversation_id
            or not self.request_id
        ):
            raise ValueError("tool execution context requires trusted identifiers")
        if not self.username:
            object.__setattr__(self, "username", self.user_id)
        if not self.run_id:
            object.__setattr__(self, "run_id", self.request_id)
        if self.authorized_resources != self.workspace_route.resource_scope:
            raise ValueError("authorized resources must come from workspace route")
        if self.conversation_mode not in {"normal", "no_write", "isolated"}:
            raise ValueError("invalid conversation mode")
