"""Static workspace admission registry."""

from __future__ import annotations

from dataclasses import dataclass

from backend.core.router.errors import WorkspaceAccessDenied
from backend.core.router.models import TrustedIdentity, WorkspaceType


@dataclass(frozen=True, slots=True)
class WorkspaceRegistration:
    workspace_type: WorkspaceType
    allowed_roles: frozenset[str]
    profile_id: str
    prompt_key: str
    profile_policy: str
    memory_policy_id: str
    action_policy: str


WORKSPACE_REGISTRY: dict[WorkspaceType, WorkspaceRegistration] = {
    "learning": WorkspaceRegistration(
        "learning", frozenset({"student"}), "learning.default.v1",
        "learning.v1", "learning.v1", "learning.v1", "learning.v1",
    ),
    "teaching": WorkspaceRegistration(
        "teaching", frozenset({"teacher"}), "teaching.default.v1",
        "teaching.v1", "teaching.v1", "teaching.v1", "teaching.v1",
    ),
    "research": WorkspaceRegistration(
        "research", frozenset({"student", "teacher"}), "research.default.v1",
        "research.v1", "research.v1", "research.v1", "research.v1",
    ),
}


def resolve_workspace(
    identity: TrustedIdentity,
    workspace_type: str,
) -> WorkspaceRegistration:
    registration = WORKSPACE_REGISTRY.get(workspace_type)  # type: ignore[arg-type]
    if registration is None:
        raise WorkspaceAccessDenied(f"unsupported workspace: {workspace_type!r}")
    if identity.account_role not in registration.allowed_roles:
        raise WorkspaceAccessDenied(
            f"role {identity.account_role!r} cannot access {workspace_type!r}"
        )
    return registration

