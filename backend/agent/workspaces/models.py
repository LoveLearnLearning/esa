"""Immutable contracts used to compile one workspace agent turn."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping, Protocol

from backend.agent.workspaces.routing import TrustedIdentity, WorkspaceRoute


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
    max_iterations: int
    tool_timeout_seconds: float
    parallel_tools: bool = False
    tool_error_policy: str = "return_structured_error"

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
    loop_policy: LoopPolicy
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
    action_names: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class RunManifest:
    run_id: str
    request_id: str
    runtime_identity: str
    conversation_id: str
    workspace_type: str
    definition_version: int
    agent_profile_id: str
    prompt_version: str
    context_fingerprint: str
    capability_fingerprint: str
    resource_references: tuple[str, ...]
    resource_revisions: Mapping[str, str]
    policy_versions: Mapping[str, str]
    conversation_mode: str
    tool_names: tuple[str, ...]
    action_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("run_id", "request_id", "runtime_identity"):
            if not getattr(self, field_name):
                raise ValueError(f"manifest {field_name} is required")
        object.__setattr__(self, "resource_references", tuple(self.resource_references))
        object.__setattr__(self, "resource_revisions", _mapping(self.resource_revisions))
        object.__setattr__(self, "policy_versions", _mapping(self.policy_versions))
        object.__setattr__(self, "tool_names", tuple(self.tool_names))
        object.__setattr__(self, "action_names", tuple(self.action_names))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "request_id": self.request_id,
            "runtime_identity": self.runtime_identity,
            "conversation_id": self.conversation_id,
            "workspace_type": self.workspace_type,
            "definition_version": self.definition_version,
            "agent_profile_id": self.agent_profile_id,
            "prompt_version": self.prompt_version,
            "context_fingerprint": self.context_fingerprint,
            "capability_fingerprint": self.capability_fingerprint,
            "resource_references": list(self.resource_references),
            "resource_revisions": dict(self.resource_revisions),
            "policy_versions": dict(self.policy_versions),
            "conversation_mode": self.conversation_mode,
            "tool_names": list(self.tool_names),
            "action_names": list(self.action_names),
        }

    def to_run_metadata(self) -> Mapping[str, Any]:
        return _mapping(
            {
                **self.to_dict(),
                "profile_fingerprint": (
                    f"{self.agent_profile_id}:{self.definition_version}"
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class AgentRunSpec:
    messages: tuple[Mapping[str, Any], ...]
    tool_schemas: tuple[Mapping[str, Any], ...]
    loop_policy: LoopPolicy
    manifest: RunManifest

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(_mapping(item) for item in self.messages))
        object.__setattr__(
            self, "tool_schemas", tuple(_mapping(item) for item in self.tool_schemas)
        )

    @property
    def capability_fingerprint(self) -> str:
        return self.manifest.capability_fingerprint

    @property
    def run_metadata(self) -> Mapping[str, Any]:
        return self.manifest.to_run_metadata()

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": [dict(item) for item in self.messages],
            "tool_schemas": [dict(item) for item in self.tool_schemas],
            "loop_policy": asdict(self.loop_policy),
            "manifest": self.manifest.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class BoundExecutionContext:
    tool_executor: ToolExecutor
    execution_context: Any


@dataclass(frozen=True, slots=True)
class ExecutableAgentRun:
    spec: AgentRunSpec
    binding: BoundExecutionContext

    @property
    def messages(self):
        return self.spec.messages

    @property
    def tool_schemas(self):
        return self.spec.tool_schemas

    @property
    def loop_policy(self):
        return self.spec.loop_policy

    @property
    def capability_fingerprint(self):
        return self.spec.capability_fingerprint

    @property
    def run_metadata(self):
        return self.spec.run_metadata

    @property
    def tool_executor(self):
        return self.binding.tool_executor

    @property
    def execution_context(self):
        return self.binding.execution_context


ToolHandler = Callable[..., Any | Awaitable[Any]]
