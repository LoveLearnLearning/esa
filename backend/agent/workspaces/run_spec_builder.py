"""Deterministically compile context and capabilities into an AgentRunSpec."""

from __future__ import annotations

from backend.agent.tools.context import ToolExecutionContext
from backend.agent.workspaces.capability_runtime import CompiledCapabilityView
from backend.agent.workspaces.models import (
    AgentRunSpec,
    AgentTurnInput,
    ComposedContext,
    WorkspaceRuntimeProfile,
)


class RunSpecBuilder:
    def build(
        self,
        *,
        turn: AgentTurnInput,
        profile: WorkspaceRuntimeProfile,
        context: ComposedContext,
        capabilities: CompiledCapabilityView,
        execution_context: ToolExecutionContext,
    ) -> AgentRunSpec:
        messages = (
            {"role": "system", "content": context.rendered},
            *turn.history,
            {"role": "user", "content": turn.current_message},
        )
        metadata = {
            "request_id": execution_context.request_id,
            "conversation_id": turn.conversation_id,
            "workspace_type": turn.route.workspace_type,
            "agent_profile_id": profile.profile_id,
            "profile_fingerprint": f"{profile.profile_id}:{profile.version}",
            "capability_fingerprint": capabilities.capabilities.fingerprint,
            "prompt_version": profile.prompt_key,
            "tool_names": tuple(sorted(capabilities.capabilities.tool_names)),
        }
        return AgentRunSpec(
            messages=messages,
            tool_schemas=capabilities.capabilities.tool_schemas,
            tool_executor=capabilities.bind(execution_context),
            execution_context=execution_context,
            loop_policy=profile.loop_policy,
            capability_fingerprint=capabilities.capabilities.fingerprint,
            run_metadata=metadata,
        )

