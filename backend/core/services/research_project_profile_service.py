# backend/core/services/research_project_profile_service.py

"""Ownership-checked research project profile service."""

from __future__ import annotations


class ResearchProjectProfileService:
    """提供 `research project profile service` 领域服务。"""
    def __init__(self, profile_store, project_store) -> None:
        """初始化 `ResearchProjectProfileService` 实例。"""
        self.profile_store = profile_store
        self.project_store = project_store

    def _project(self, project_id: str, user_id: str) -> dict:
        """处理 `_project` 相关逻辑。"""
        project = self.project_store.get_project(project_id,user_id)
        if project is None:
            raise KeyError(project_id)
        return project

    def get(self, project_id: str, user_id: str) -> dict | None:
        """获取 `get` 相关数据。

        Args:
            project_id: str => 项目 ID。
            user_id: str => 用户 ID。

        Returns:
            dict | None => 处理结果。
        """
        self._project(project_id,user_id)
        return self.profile_store.get(project_id,user_id)

    def upsert(self, project_id: str, user_id: str, *, agent_instructions: str,
               expected_revision: int | None = None) -> dict:
        """处理 `upsert` 相关逻辑。

        Args:
            project_id: str => 项目 ID。
            user_id: str => 用户 ID。
            agent_instructions: str => `agent_instructions` 参数。
            expected_revision: int | None => `expected_revision` 参数。

        Returns:
            dict => 处理结果。
        """
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
