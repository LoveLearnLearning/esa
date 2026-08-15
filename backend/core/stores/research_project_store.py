# backend/core/stores/research_project_store.py

"""提供数据持久化实现。"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


class ResearchProjectStore(BaseSQLiteStore):
    """Persistent, user-scoped research projects."""

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        """初始化 `ResearchProjectStore` 实例。"""
        super().__init__(database_path)

    def _initialize(self) -> None:
        """初始化 `initialize` 相关数据。"""
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS research_projects (
                    project_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    CHECK(status IN ('active', 'archived'))
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_research_projects_user
                ON research_projects (user_id, status, updated_at)
                """
            )

    @staticmethod
    def _now() -> str:
        """处理 `_now` 相关逻辑。"""
        return datetime.now(timezone.utc).isoformat()

    def create_project(
        self,
        user_id: str,
        name: str,
        description: str = "",
    ) -> dict:
        """创建 `project` 相关数据。

        Args:
            user_id: str => 用户 ID。
            name: str => `name` 参数。
            description: str => `description` 参数。

        Returns:
            dict => 处理结果。
        """
        now = self._now()
        project = {
            "project_id": str(uuid.uuid4()),
            "user_id": user_id,
            "name": name,
            "description": description,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        self.execute(
            """
            INSERT INTO research_projects (
                project_id, user_id, name, description, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(project.values()),
        )
        return project

    def list_projects(
        self,
        user_id: str,
        *,
        include_archived: bool = False,
    ) -> list[dict]:
        """列出 `projects` 相关数据。

        Args:
            user_id: str => 用户 ID。
            include_archived: bool => `include_archived` 参数。

        Returns:
            list[dict] => 处理结果。
        """
        sql = """
            SELECT project_id, user_id, name, description, status,
                   created_at, updated_at
            FROM research_projects
            WHERE user_id = ?
        """
        params: tuple = (user_id,)
        if not include_archived:
            sql += " AND status = 'active'"
        sql += " ORDER BY updated_at DESC"
        return [dict(row) for row in self.query_all(sql, params)]

    def get_project(self, project_id: str, user_id: str) -> dict | None:
        """获取 `project` 相关数据。

        Args:
            project_id: str => 项目 ID。
            user_id: str => 用户 ID。

        Returns:
            dict | None => 处理结果。
        """
        row = self.query_one(
            """
            SELECT project_id, user_id, name, description, status,
                   created_at, updated_at
            FROM research_projects
            WHERE project_id = ? AND user_id = ?
            """,
            (project_id, user_id),
        )
        return dict(row) if row is not None else None

    def update_project(
        self,
        project_id: str,
        user_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
    ) -> dict | None:
        """更新 `project` 相关数据。

        Args:
            project_id: str => 项目 ID。
            user_id: str => 用户 ID。
            name: str | None => `name` 参数。
            description: str | None => `description` 参数。
            status: str | None => `status` 参数。

        Returns:
            dict | None => 处理结果。
        """
        current = self.get_project(project_id, user_id)
        if current is None:
            return None
        next_name = current["name"] if name is None else name
        next_description = (
            current["description"] if description is None else description
        )
        next_status = current["status"] if status is None else status
        try:
            self.execute(
                """
                UPDATE research_projects
                SET name = ?, description = ?, status = ?, updated_at = ?
                WHERE project_id = ? AND user_id = ?
                """,
                (
                    next_name,
                    next_description,
                    next_status,
                    self._now(),
                    project_id,
                    user_id,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("invalid research project status") from error
        return self.get_project(project_id, user_id)
