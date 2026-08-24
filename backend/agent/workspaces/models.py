# backend/agent/workspaces/models.py

"""Immutable contracts used to compile one workspace agent turn."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping, Protocol

from backend.agent.workspaces.routing import TrustedIdentity, WorkspaceRoute


def _mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """处理 `_mapping` 相关逻辑。"""
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True, slots=True)
class ContextSection:
    """封装 `ContextSection` 的状态与行为。"""
    key: str
    title: str
    content: str
    trust: str
    order: int
    stable: bool = False


@dataclass(frozen=True, slots=True)
class ComposedContext:
    """封装 `ComposedContext` 的状态与行为。"""
    sections: tuple[ContextSection, ...]
    rendered: str
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class LoopPolicy:
    """封装 `LoopPolicy` 的状态与行为。"""
    max_iterations: int
    tool_timeout_seconds: float
    parallel_tools: bool = False
    tool_error_policy: str = "return_structured_error"

    def __post_init__(self) -> None:
        """完成实例初始化后的校验与派生字段构建。"""
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        if self.tool_timeout_seconds <= 0:
            raise ValueError("tool_timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class WorkspaceRuntimeProfile:
    """封装 `WorkspaceRuntimeProfile` 的状态与行为。"""
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
    """表示 `agent turn input` 数据结构。"""
    route: WorkspaceRoute
    identity: TrustedIdentity
    conversation_id: str
    current_message: str
    task_mode: str | None = None
    history: tuple[Mapping[str, Any], ...] = ()
    conversation_summary: str = ""
    conversation_mode: str = "normal"
    user_preferences: Mapping[str, Any] = field(default_factory=dict)
    group_context: Mapping[str, Any] = field(default_factory=dict)
    workspace_profile_context: str = ""
    profile_snapshot: Any | None = None
    learning_context: "LearningTurnContext" = field(
        default_factory=lambda: LearningTurnContext()
    )
    authorized_attachments: tuple[Mapping[str, Any], ...] = ()
    request_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """完成实例初始化后的校验与派生字段构建。"""
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


@dataclass(frozen=True, slots=True)
class LearningTurnContext:
    """Server-resolved learning identifiers available to one Agent turn."""

    resolved_kp_ids: tuple[str, ...] = ()
    pending_practice_kp_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resolved_kp_ids",
            tuple(kp_id for kp_id in self.resolved_kp_ids if kp_id),
        )


class ToolExecutor(Protocol):
    """定义 `ToolExecutor` 组件协议。"""
    async def execute(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """执行 `execute` 相关数据。

        Args:
            name: str => `name` 参数。
            arguments: Mapping[str, Any] => `arguments` 参数。

        Returns:
            Any => 处理结果。
        """
        ...


@dataclass(frozen=True, slots=True)
class ResolvedCapabilities:
    """封装 `ResolvedCapabilities` 的状态与行为。"""
    skill_index: str
    autoload_skills: str
    tool_schemas: tuple[Mapping[str, Any], ...]
    skill_names: frozenset[str]
    tool_names: frozenset[str]
    fingerprint: str
    action_names: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class RunManifest:
    """记录一次 Agent 运行所使用的身份、策略、资源和能力版本。"""
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
        """校验标识符并冻结清单中的集合与映射。"""
        for field_name in ("run_id", "request_id", "runtime_identity"):
            if not getattr(self, field_name):
                raise ValueError(f"manifest {field_name} is required")
        object.__setattr__(self, "resource_references", tuple(self.resource_references))
        object.__setattr__(self, "resource_revisions", _mapping(self.resource_revisions))
        object.__setattr__(self, "policy_versions", _mapping(self.policy_versions))
        object.__setattr__(self, "tool_names", tuple(self.tool_names))
        object.__setattr__(self, "action_names", tuple(self.action_names))

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。"""
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
        """转换为运行时只读元数据。"""
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
    """封装 `AgentRunSpec` 的状态与行为。"""
    messages: tuple[Mapping[str, Any], ...]
    tool_schemas: tuple[Mapping[str, Any], ...]
    loop_policy: LoopPolicy
    manifest: RunManifest

    def __post_init__(self) -> None:
        """完成实例初始化后的校验与派生字段构建。"""
        object.__setattr__(self, "messages", tuple(_mapping(item) for item in self.messages))
        object.__setattr__(
            self, "tool_schemas", tuple(_mapping(item) for item in self.tool_schemas)
        )

    @property
    def capability_fingerprint(self) -> str:
        """返回本次运行的能力指纹。"""
        return self.manifest.capability_fingerprint

    @property
    def run_metadata(self) -> Mapping[str, Any]:
        """返回本次运行的只读元数据。"""
        return self.manifest.to_run_metadata()

    def to_dict(self) -> dict[str, Any]:
        """转换为不包含执行器对象的可序列化结构。"""
        return {
            "messages": [dict(item) for item in self.messages],
            "tool_schemas": [dict(item) for item in self.tool_schemas],
            "loop_policy": asdict(self.loop_policy),
            "manifest": self.manifest.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class BoundExecutionContext:
    """绑定工具执行器和可信的单轮执行上下文。"""
    tool_executor: ToolExecutor
    execution_context: Any


@dataclass(frozen=True, slots=True)
class ExecutableAgentRun:
    """组合可序列化运行规范与不可序列化执行绑定。"""
    spec: AgentRunSpec
    binding: BoundExecutionContext

    @property
    def messages(self):
        """代理访问运行规范中的消息。"""
        return self.spec.messages

    @property
    def tool_schemas(self):
        """代理访问运行规范中的工具 Schema。"""
        return self.spec.tool_schemas

    @property
    def loop_policy(self):
        """代理访问运行循环策略。"""
        return self.spec.loop_policy

    @property
    def capability_fingerprint(self):
        """代理访问能力指纹。"""
        return self.spec.capability_fingerprint

    @property
    def run_metadata(self):
        """代理访问运行元数据。"""
        return self.spec.run_metadata

    @property
    def tool_executor(self):
        """返回已绑定的工具执行器。"""
        return self.binding.tool_executor

    @property
    def execution_context(self):
        """返回已绑定的可信工具上下文。"""
        return self.binding.execution_context


ToolHandler = Callable[..., Any | Awaitable[Any]]
