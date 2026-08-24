# backend/agent/workspaces/runtime.py

"""Workspace runtime pipeline producing the only input consumed by Agent."""

from __future__ import annotations

from backend.agent.tools.context import AgentRuntimeDependencies, ToolExecutionContext
from backend.agent.workspaces.capability_runtime import CapabilityRuntime
from backend.agent.workspaces.context_composer import ContextComposer, StrategyAugmentation
from backend.agent.workspaces.definitions import get_workspace_definition
from backend.agent.workspaces.learning_adapter import LearningAdapter
from backend.agent.workspaces.models import AgentRunSpec, AgentTurnInput, ExecutableAgentRun
from backend.agent.workspaces.profile_registry import DEFAULT_PROFILE_REGISTRY, WorkspaceProfileRegistry
from backend.agent.workspaces.run_spec_builder import RunSpecBuilder


class WorkspaceRuntime:
    """封装 `WorkspaceRuntime` 的状态与行为。"""
    def __init__(
        self,
        dependencies: AgentRuntimeDependencies,
        *,
        profiles: WorkspaceProfileRegistry = DEFAULT_PROFILE_REGISTRY,
    ) -> None:
        """初始化 `WorkspaceRuntime` 实例。"""
        self.dependencies = dependencies
        self.profiles = profiles
        self.capabilities = CapabilityRuntime()
        self.composer = ContextComposer()
        self.learning = LearningAdapter()
        self.builder = RunSpecBuilder()

    def prepare(self, turn: AgentTurnInput) -> ExecutableAgentRun:
        """准备 `prepare` 相关数据。

        Args:
            turn: AgentTurnInput => `turn` 参数。

        Returns:
            ExecutableAgentRun => 已绑定工具执行上下文的运行对象。
        """
        route = turn.route
        profile = self.profiles.resolve(route.agent_profile_id, route.workspace_type)
        route_configuration = (
            route.prompt_key,
            route.skill_scopes,
            route.tool_scopes,
            route.profile_policy,
            route.memory_policy_id,
            route.action_policy,
        )
        profile_configuration = (
            profile.prompt_key,
            profile.skill_scopes,
            profile.tool_scopes,
            profile.profile_policy,
            profile.memory_policy_id,
            profile.action_policy,
        )
        if route_configuration != profile_configuration:
            raise ValueError("workspace route does not match runtime profile")
        definition = get_workspace_definition(route.workspace_type)
        declared_resources = (
            definition.required_resource_capabilities
            | definition.optional_resource_capabilities
        )
        if not definition.required_resource_capabilities <= route.resource_scope.capabilities:
            raise ValueError("workspace required resource capabilities are missing")
        undeclared = route.resource_scope.capabilities - declared_resources
        if undeclared:
            raise ValueError(
                f"undeclared resource capabilities: {', '.join(sorted(undeclared))}"
            )
        view = self.capabilities.compile(
            skill_scopes=route.skill_scopes,
            tool_scopes=route.tool_scopes,
            profile_fingerprint=f"{profile.profile_id}:{profile.version}",
            policy_versions=(profile.profile_policy, profile.memory_policy_id, profile.action_policy),
            resource_capabilities=route.resource_scope.capabilities,
            conversation_mode=turn.conversation_mode,
            has_research_project=route.resource_scope.project_id is not None,
            has_attachments=bool(route.resource_scope.attachment_ids),
            knowledge_sources=turn.knowledge_sources,
        )
        strategy = (
            self.learning.augment(turn, view.skills, turn.profile_snapshot)
            if route.workspace_type == "learning"
            else StrategyAugmentation()
        )
        composed = self.composer.compose(turn, profile, view.capabilities, strategy)
        request_id = str(turn.request_metadata.get("request_id", "")).strip()
        if not request_id:
            raise ValueError("request_id is required")
        execution_context = ToolExecutionContext(
            user_id=turn.identity.user_id,
            username=turn.identity.username,
            conversation_id=turn.conversation_id,
            workspace_route=route,
            authorized_resources=route.resource_scope,
            conversation_mode=turn.conversation_mode,
            runtime_dependencies=self.dependencies,
            request_id=request_id,
            run_id=str(turn.request_metadata.get("run_id") or request_id),
            total_weeks=turn.request_metadata.get("total_weeks"),
            knowledge_sources=turn.knowledge_sources,
        )
        return self.builder.build(
            turn=turn,
            profile=profile,
            context=composed,
            capabilities=view,
            execution_context=execution_context,
        )

    def prepare_evaluation(self, turn: AgentTurnInput) -> AgentRunSpec:
        """Compile evaluation data through the exact production compiler path."""

        return self.prepare(turn).spec
