"""Workspace runtime pipeline producing the only input consumed by Agent."""

from __future__ import annotations

from backend.agent.tools.context import AgentRuntimeDependencies, ToolExecutionContext
from backend.agent.workspaces.capability_runtime import CapabilityRuntime
from backend.agent.workspaces.context_composer import ContextComposer, StrategyAugmentation
from backend.agent.workspaces.learning_adapter import LearningAdapter
from backend.agent.workspaces.models import AgentRunSpec, AgentTurnInput
from backend.agent.workspaces.profile_registry import DEFAULT_PROFILE_REGISTRY, WorkspaceProfileRegistry
from backend.agent.workspaces.run_spec_builder import RunSpecBuilder


class WorkspaceRuntime:
    def __init__(
        self,
        dependencies: AgentRuntimeDependencies,
        *,
        profiles: WorkspaceProfileRegistry = DEFAULT_PROFILE_REGISTRY,
    ) -> None:
        self.dependencies = dependencies
        self.profiles = profiles
        self.capabilities = CapabilityRuntime()
        self.composer = ContextComposer()
        self.learning = LearningAdapter()
        self.builder = RunSpecBuilder()

    def prepare(self, turn: AgentTurnInput) -> AgentRunSpec:
        route = turn.route
        profile = self.profiles.resolve(route.agent_profile_id, route.workspace_type)
        if not profile.skill_scopes.issuperset(route.skill_scopes):
            raise ValueError("route skill scopes exceed runtime profile")
        if not profile.tool_scopes.issuperset(route.tool_scopes):
            raise ValueError("route tool scopes exceed runtime profile")
        view = self.capabilities.compile(
            skill_scopes=route.skill_scopes & profile.skill_scopes,
            tool_scopes=route.tool_scopes & profile.tool_scopes,
            profile_fingerprint=f"{profile.profile_id}:{profile.version}",
            policy_versions=(profile.profile_policy, profile.memory_policy_id, profile.action_policy),
            resource_capabilities=route.resource_scope.capabilities,
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
            conversation_id=turn.conversation_id,
            workspace_route=route,
            authorized_resources=route.resource_scope,
            conversation_mode=turn.conversation_mode,
            runtime_dependencies=self.dependencies,
            request_id=request_id,
        )
        return self.builder.build(
            turn=turn,
            profile=profile,
            context=composed,
            capabilities=view,
            execution_context=execution_context,
        )
