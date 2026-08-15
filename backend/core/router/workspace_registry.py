# backend/core/router/workspace_registry.py

"""Static workspace admission registry."""

from __future__ import annotations

from backend.agent.workspaces.definitions import (
    WORKSPACE_DEFINITIONS,
    WorkspaceDefinition,
)
from backend.core.router.errors import WorkspaceAccessDenied
from backend.core.router.models import TrustedIdentity

WorkspaceRegistration = WorkspaceDefinition
WORKSPACE_REGISTRY = WORKSPACE_DEFINITIONS


def resolve_workspace(
    identity: TrustedIdentity,
    workspace_type: str,
) -> WorkspaceRegistration:
    """解析 `workspace` 相关数据。

    Args:
        identity: TrustedIdentity => `identity` 参数。
        workspace_type: str => `workspace_type` 参数。

    Returns:
        WorkspaceRegistration => 处理结果。
    """
    registration = WORKSPACE_REGISTRY.get(workspace_type)  # type: ignore[arg-type]
    if registration is None:
        raise WorkspaceAccessDenied(f"unsupported workspace: {workspace_type!r}")
    if identity.account_role not in registration.allowed_roles:
        raise WorkspaceAccessDenied(
            f"role {identity.account_role!r} cannot access {workspace_type!r}"
        )
    return registration
