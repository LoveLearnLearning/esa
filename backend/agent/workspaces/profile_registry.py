"""Versioned, fail-closed workspace runtime profile registry."""

from __future__ import annotations

from backend.agent.workspaces.models import WorkspaceRuntimeProfile
from backend.agent.workspaces.profiles import (
    LEARNING_PROFILE,
    RESEARCH_PROFILE,
    TEACHING_PROFILE,
)


class WorkspaceProfileError(RuntimeError):
    pass


class WorkspaceProfileRegistry:
    def __init__(self, profiles: tuple[WorkspaceRuntimeProfile, ...] | None = None) -> None:
        selected = profiles or (
            LEARNING_PROFILE,
            TEACHING_PROFILE,
            RESEARCH_PROFILE,
        )
        self._profiles: dict[str, WorkspaceRuntimeProfile] = {}
        for profile in selected:
            if profile.profile_id in self._profiles:
                raise WorkspaceProfileError(f"duplicate profile: {profile.profile_id}")
            if profile.workspace_type not in profile.skill_scopes:
                raise WorkspaceProfileError(f"profile {profile.profile_id} lacks skill scope")
            if profile.workspace_type not in profile.tool_scopes:
                raise WorkspaceProfileError(f"profile {profile.profile_id} lacks tool scope")
            self._profiles[profile.profile_id] = profile

    def resolve(self, profile_id: str, workspace_type: str) -> WorkspaceRuntimeProfile:
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise WorkspaceProfileError(f"unknown workspace profile: {profile_id}")
        if profile.workspace_type != workspace_type:
            raise WorkspaceProfileError("workspace profile does not match route")
        return profile

    @property
    def profile_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._profiles))


DEFAULT_PROFILE_REGISTRY = WorkspaceProfileRegistry()

