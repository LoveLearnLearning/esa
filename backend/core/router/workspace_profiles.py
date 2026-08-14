"""Map an admitted workspace and resource state to an agent profile route."""

from __future__ import annotations

from backend.core.router.models import ResourceScope, WorkspaceRoute
from backend.core.router.workspace_registry import WorkspaceRegistration


def build_workspace_route(
    registration: WorkspaceRegistration,
    resource_scope: ResourceScope,
) -> WorkspaceRoute:
    workspace = registration.workspace_type
    return WorkspaceRoute(
        workspace_type=workspace,
        agent_profile_id=registration.profile_id,
        skill_scopes=registration.skill_scopes,
        tool_scopes=registration.tool_scopes,
        prompt_key=registration.prompt_key,
        profile_policy=registration.profile_policy,
        memory_policy_id=registration.memory_policy_id,
        resource_scope=resource_scope,
        action_policy=registration.action_policy,
    )
