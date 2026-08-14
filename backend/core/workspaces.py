"""Workspace manifest and role policy derived from canonical definitions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, TypeAlias

from backend.agent.workspaces.definitions import WORKSPACE_DEFINITIONS

AccountRole: TypeAlias = Literal["student", "teacher"]
WorkspaceType: TypeAlias = Literal["learning", "teaching", "research"]

VALID_ACCOUNT_ROLES = frozenset({"student", "teacher"})
VALID_WORKSPACE_TYPES = frozenset(WORKSPACE_DEFINITIONS)


@dataclass(frozen=True, slots=True)
class WorkspaceDescriptor:
    type: WorkspaceType
    name: str
    description: str
    capabilities: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["capabilities"] = list(self.capabilities)
        return payload


WORKSPACE_CATALOG: dict[WorkspaceType, WorkspaceDescriptor] = {
    workspace_type: WorkspaceDescriptor(
        type=workspace_type,
        name=definition.display_name,
        description=definition.description,
        capabilities=definition.manifest_capabilities,
    )
    for workspace_type, definition in WORKSPACE_DEFINITIONS.items()
}

ROLE_WORKSPACES: dict[AccountRole, tuple[WorkspaceType, ...]] = {
    role: tuple(
        workspace_type
        for workspace_type, definition in WORKSPACE_DEFINITIONS.items()
        if role in definition.allowed_roles
    )
    for role in VALID_ACCOUNT_ROLES
}


class WorkspaceAccessPolicy:
    @staticmethod
    def allowed_workspaces(account_role: str) -> tuple[WorkspaceType, ...]:
        if account_role not in VALID_ACCOUNT_ROLES:
            return ()
        return ROLE_WORKSPACES[account_role]  # type: ignore[index]

    @classmethod
    def can_access(cls, account_role: str, workspace_type: str) -> bool:
        return workspace_type in cls.allowed_workspaces(account_role)

    @classmethod
    def manifest(cls, account_role: str) -> dict[str, object]:
        allowed = cls.allowed_workspaces(account_role)
        if not allowed:
            raise ValueError(f"unsupported account role: {account_role!r}")
        return {
            "account_role": account_role,
            "default_workspace": allowed[0],
            "workspaces": [WORKSPACE_CATALOG[item].to_payload() for item in allowed],
        }


def workspace_prompt(workspace_type: str) -> str:
    from backend.core.message.prompts import WORKSPACE_PROMPTS

    definition = WORKSPACE_DEFINITIONS.get(
        workspace_type, WORKSPACE_DEFINITIONS["learning"]
    )
    return WORKSPACE_PROMPTS[definition.prompt_key]
