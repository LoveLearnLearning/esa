# backend/agent/workspaces/run_spec_builder.py

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
    """封装 `RunSpecBuilder` 的状态与行为。"""
    def build(
        self,
        *,
        turn: AgentTurnInput,
        profile: WorkspaceRuntimeProfile,
        context: ComposedContext,
        capabilities: CompiledCapabilityView,
        execution_context: ToolExecutionContext,
    ) -> AgentRunSpec:
        """构建 `build` 相关数据。

        Args:
            turn: AgentTurnInput => `turn` 参数。
            profile: WorkspaceRuntimeProfile => `profile` 参数。
            context: ComposedContext => `context` 参数。
            capabilities: CompiledCapabilityView => `capabilities` 参数。
            execution_context: ToolExecutionContext => `execution_context` 参数。

        Returns:
            AgentRunSpec => 处理结果。
        """
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
