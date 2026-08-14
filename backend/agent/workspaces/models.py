"""Immutable contracts used to compile one workspace agent turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping, Protocol

from backend.core.router.models import TrustedIdentity, WorkspaceRoute


def _mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True, slots=True)
class ContextSection:
    key: str
    title: str
    content: str
    trust: str
    order: int
    stable: bool = False


@dataclass(frozen=True, slots=True)
class ComposedContext:
    sections: tuple[ContextSection, ...]
    rendered: str
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class LoopPolicy:
    max_iterations: int = 3
    parallel_tools: bool = False
    tool_error_policy: str = "return_structured_error"
    tool_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        if self.tool_timeout_seconds <= 0:
            raise ValueError("tool_timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class WorkspaceRuntimeProfile:
    profile_id: str
    workspace_type: str
    prompt_key: str
    skill_scopes: frozenset[str]
    tool_scopes: frozenset[str]
    context_policy: frozenset[str]
    profile_policy: str
    memory_policy_id: str
    action_policy: str
    loop_policy: LoopPolicy = LoopPolicy()
    version: int = 1


@dataclass(frozen=True, slots=True)
class AgentTurnInput:
    route: WorkspaceRoute
    identity: TrustedIdentity
    conversation_id: str
    current_message: str
    history: tuple[Mapping[str, Any], ...] = ()
    conversation_summary: str = ""
    conversation_mode: str = "normal"
    user_preferences: Mapping[str, Any] = field(default_factory=dict)
    group_context: Mapping[str, Any] = field(default_factory=dict)
    workspace_profile_context: str = ""
    profile_snapshot: Any | None = None
    authorized_attachments: tuple[Mapping[str, Any], ...] = ()
    request_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.conversation_id != self.route.resource_scope.metadata.get(
            "conversation_id", self.conversation_id
        ):
            raise ValueError("turn conversation does not match route")
        if self.conversation_mode not in {"normal", "no_write", "isolated"}:
            raise ValueError("invalid conversation mode")
        object.__setattr__(self, "history", tuple(_mapping(item) for item in self.history))
        object.__setattr__(self, "user_preferences", _mapping(self.user_preferences))
        object.__setattr__(self, "group_context", _mapping(self.group_context))
        object.__setattr__(
            self,
            "authorized_attachments",
            tuple(_mapping(item) for item in self.authorized_attachments),
        )
        object.__setattr__(self, "request_metadata", _mapping(self.request_metadata))


class ToolExecutor(Protocol):
    async def execute(self, name: str, arguments: Mapping[str, Any]) -> Any: ...


@dataclass(frozen=True, slots=True)
class ResolvedCapabilities:
    skill_index: str
    autoload_skills: str
    tool_schemas: tuple[Mapping[str, Any], ...]
    skill_names: frozenset[str]
    tool_names: frozenset[str]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class AgentRunSpec:
    messages: tuple[Mapping[str, Any], ...]
    tool_schemas: tuple[Mapping[str, Any], ...]
    tool_executor: ToolExecutor
    execution_context: Any
    loop_policy: LoopPolicy
    capability_fingerprint: str
    run_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(_mapping(item) for item in self.messages))
        object.__setattr__(
            self, "tool_schemas", tuple(_mapping(item) for item in self.tool_schemas)
        )
        object.__setattr__(self, "run_metadata", _mapping(self.run_metadata))


ToolHandler = Callable[..., Any | Awaitable[Any]]
