"""Deterministically compile context and capabilities into an AgentRunSpec."""

from __future__ import annotations

import hashlib

from backend.agent.tools.context import ToolExecutionContext
from backend.agent.workspaces.capability_runtime import CompiledCapabilityView
from backend.agent.workspaces.history import sanitize_qwen_history
from backend.agent.workspaces.models import (
    AgentRunSpec,
    AgentTurnInput,
    BoundExecutionContext,
    ComposedContext,
    ExecutableAgentRun,
    RunManifest,
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
    ) -> ExecutableAgentRun:
        messages = (
            {"role": "system", "content": context.rendered},
            *sanitize_qwen_history(turn.history),
            {"role": "user", "content": turn.current_message},
        )
        route = turn.route
        resources = route.resource_scope
        resource_references = tuple(
            item
            for item in (
                f"project:{resources.project_id}" if resources.project_id else "",
                f"class:{resources.class_id}" if resources.class_id else "",
                f"assignment:{resources.assignment_id}" if resources.assignment_id else "",
                *(f"attachment:{item}" for item in resources.attachment_ids),
            )
            if item
        )
        manifest = RunManifest(
            run_id=str(turn.request_metadata.get("run_id") or execution_context.request_id),
            request_id=execution_context.request_id,
            runtime_identity=turn.identity.user_id,
            conversation_id=turn.conversation_id,
            workspace_type=route.workspace_type,
            definition_version=profile.version,
            agent_profile_id=profile.profile_id,
            prompt_version=profile.prompt_key,
            context_fingerprint=hashlib.sha256(
                context.rendered.encode("utf-8")
            ).hexdigest(),
            capability_fingerprint=capabilities.capabilities.fingerprint,
            resource_references=resource_references,
            resource_revisions=dict(getattr(resources, "revision_set", {})),
            policy_versions={
                "profile": profile.profile_policy,
                "memory": profile.memory_policy_id,
                "action": profile.action_policy,
                "resource": str(getattr(resources, "policy_version", "")),
            },
            conversation_mode=turn.conversation_mode,
            tool_names=tuple(sorted(capabilities.capabilities.tool_names)),
            action_names=tuple(sorted(capabilities.capabilities.action_names)),
        )
        spec = AgentRunSpec(
            messages=messages,
            tool_schemas=capabilities.capabilities.tool_schemas,
            loop_policy=profile.loop_policy,
            manifest=manifest,
        )
        return ExecutableAgentRun(
            spec=spec,
            binding=BoundExecutionContext(
                tool_executor=capabilities.bind(execution_context),
                execution_context=execution_context,
            ),
        )
