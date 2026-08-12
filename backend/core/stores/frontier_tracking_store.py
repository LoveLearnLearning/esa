from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


class FrontierTrackingStore(BaseSQLiteStore):
    """Persistent queue and results for research-frontier tracking jobs."""

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        super().__init__(database_path)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS research_frontier_jobs (
                    job_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    time_window_years INTEGER NOT NULL DEFAULT 5,
                    max_results INTEGER NOT NULL DEFAULT 20,
                    status TEXT NOT NULL DEFAULT 'queued',
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY(project_id)
                        REFERENCES research_projects(project_id) ON DELETE CASCADE,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    CHECK(status IN ('queued', 'running', 'succeeded', 'failed')),
                    CHECK(time_window_years BETWEEN 1 AND 20),
                    CHECK(max_results BETWEEN 5 AND 40)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_frontier_jobs_project
                ON research_frontier_jobs(user_id, project_id, created_at DESC)
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _out(row: sqlite3.Row) -> dict:
        payload = dict(row)
        raw_result = payload.pop("result_json", None)
        payload["result"] = json.loads(raw_result) if raw_result else None
        return payload

    def create_job(
        self,
        *,
        project_id: str,
        user_id: str,
        query: str,
        time_window_years: int,
        max_results: int,
    ) -> dict:
        now = self._now()
        job_id = str(uuid.uuid4())
        self.execute(
            """
            INSERT INTO research_frontier_jobs (
                job_id, project_id, user_id, query, time_window_years,
                max_results, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)
            """,
            (
                job_id,
                project_id,
                user_id,
                query,
                time_window_years,
                max_results,
                now,
                now,
            ),
        )
        job = self.get_job(job_id, user_id)
        assert job is not None
        return job

    def get_job(self, job_id: str, user_id: str | None = None) -> dict | None:
        sql = "SELECT * FROM research_frontier_jobs WHERE job_id = ?"
        params: tuple = (job_id,)
        if user_id is not None:
            sql += " AND user_id = ?"
            params += (user_id,)
        row = self.query_one(sql, params)
        return self._out(row) if row is not None else None

    def list_jobs(self, project_id: str, user_id: str) -> list[dict]:
        rows = self.query_all(
            """
            SELECT * FROM research_frontier_jobs
            WHERE project_id = ? AND user_id = ?
            ORDER BY created_at DESC
            """,
            (project_id, user_id),
        )
        return [self._out(row) for row in rows]

    def claim_job(self, job_id: str) -> dict | None:
        now = self._now()
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE research_frontier_jobs
                SET status = 'running', started_at = ?, updated_at = ?, error = NULL
                WHERE job_id = ? AND status = 'queued'
                """,
                (now, now, job_id),
            )
            if cursor.rowcount <= 0:
                return None
            row = connection.execute(
                "SELECT * FROM research_frontier_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return self._out(row) if row is not None else None

    def complete_job(self, job_id: str, result: dict) -> None:
        now = self._now()
        self.execute(
            """
            UPDATE research_frontier_jobs
            SET status = 'succeeded', result_json = ?, error = NULL,
                completed_at = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (json.dumps(result, ensure_ascii=False), now, now, job_id),
        )

    def fail_job(self, job_id: str, error: str) -> None:
        now = self._now()
        self.execute(
            """
            UPDATE research_frontier_jobs
            SET status = 'failed', error = ?, completed_at = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (error[:1000], now, now, job_id),
        )

    def requeue_interrupted(self) -> list[str]:
        now = self._now()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE research_frontier_jobs
                SET status = 'queued', started_at = NULL, updated_at = ?
                WHERE status = 'running'
                """,
                (now,),
            )
            rows = connection.execute(
                """
                SELECT job_id FROM research_frontier_jobs
                WHERE status = 'queued'
                ORDER BY created_at
                """
            ).fetchall()
        return [row["job_id"] for row in rows]
