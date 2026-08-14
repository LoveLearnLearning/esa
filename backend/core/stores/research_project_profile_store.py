"""Revisioned research project instructions; schema is migration-owned."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.agent.memories.core_memory_models import MemoryRevisionConflict
from backend.core.stores.base_sqlite_store import BaseSQLiteStore


class ResearchProjectProfileStore(BaseSQLiteStore):
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def _initialize(self) -> None:
        raise RuntimeError("research project profile schema must be installed by migrations")

    def get(self, project_id: str, user_id: str) -> dict | None:
        row = self.query_one(
            "SELECT * FROM research_project_profiles WHERE project_id=? AND user_id=?",
            (project_id,user_id),
        )
        return dict(row) if row is not None else None

    def upsert(
        self,
        *,
        project_id: str,
        user_id: str,
        agent_instructions: str,
        expected_revision: int | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        current = self.get(project_id, user_id)
        if current is None:
            if expected_revision not in (None, 0):
                raise MemoryRevisionConflict(0)
            try:
                self.execute(
                    """INSERT INTO research_project_profiles
                       (project_id,user_id,agent_instructions,format_version,revision,created_at,updated_at)
                       VALUES (?,?,?,1,1,?,?)""",
                    (project_id, user_id, agent_instructions, now, now),
                )
            except sqlite3.IntegrityError as error:
                concurrent = self.get(project_id, user_id)
                if concurrent is not None:
                    raise MemoryRevisionConflict(int(concurrent["revision"])) from error
                raise
        else:
            if expected_revision != int(current["revision"]):
                raise MemoryRevisionConflict(int(current["revision"]))
            changed = self.execute(
                """UPDATE research_project_profiles SET agent_instructions=?,revision=revision+1,updated_at=?
                   WHERE project_id=? AND user_id=? AND revision=?""",
                (
                    agent_instructions,
                    now,
                    project_id,
                    user_id,
                    expected_revision,
                ),
            )
            if changed != 1:
                concurrent = self.get(project_id, user_id)
                raise MemoryRevisionConflict(
                    int(concurrent["revision"]) if concurrent is not None else 0
                )
        result = self.get(project_id, user_id)
        assert result is not None
        return result
