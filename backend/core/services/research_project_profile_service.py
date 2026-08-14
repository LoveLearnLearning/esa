"""Ownership-checked research project profile service."""

from __future__ import annotations


class ResearchProjectProfileService:
    def __init__(self, profile_store, project_store) -> None:
        self.profile_store = profile_store
        self.project_store = project_store

    def _project(self, project_id: str, user_id: str) -> dict:
        project = self.project_store.get_project(project_id,user_id)
        if project is None:
            raise KeyError(project_id)
        return project

    def get(self, project_id: str, user_id: str) -> dict | None:
        self._project(project_id,user_id)
        return self.profile_store.get(project_id,user_id)

    def upsert(self, project_id: str, user_id: str, *, agent_instructions: str,
               expected_revision: int | None = None) -> dict:
        project = self._project(project_id,user_id)
        if project["status"] != "active":
            raise ValueError("archived project profile cannot be changed")
        instructions = agent_instructions.strip()
        if len(instructions) > 12000:
            raise ValueError("project instructions are too long")
        return self.profile_store.upsert(
            project_id=project_id,user_id=user_id,agent_instructions=instructions,
            expected_revision=expected_revision,
        )

