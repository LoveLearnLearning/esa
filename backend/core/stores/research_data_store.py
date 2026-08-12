from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


class ResearchDataStore(BaseSQLiteStore):
    """Dataset metadata and durable analysis jobs; files remain on local disk."""

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        super().__init__(database_path)

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_datasets (
                    dataset_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    row_count INTEGER NOT NULL DEFAULT 0,
                    column_count INTEGER NOT NULL DEFAULT 0,
                    profile_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'ready',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id)
                        REFERENCES research_projects(project_id) ON DELETE CASCADE,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    CHECK(status IN ('ready', 'invalid', 'archived'))
                );
                CREATE INDEX IF NOT EXISTS idx_research_datasets_project
                ON research_datasets(user_id, project_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS research_analysis_jobs (
                    job_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    analysis_type TEXT NOT NULL,
                    parameters_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'queued',
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY(dataset_id)
                        REFERENCES research_datasets(dataset_id) ON DELETE CASCADE,
                    FOREIGN KEY(project_id)
                        REFERENCES research_projects(project_id) ON DELETE CASCADE,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    CHECK(analysis_type IN (
                        'descriptive', 'correlation', 'group_compare',
                        'text_frequency'
                    )),
                    CHECK(status IN ('queued', 'running', 'succeeded', 'failed'))
                );
                CREATE INDEX IF NOT EXISTS idx_research_analysis_jobs_dataset
                ON research_analysis_jobs(user_id, dataset_id, created_at DESC);
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _dataset_out(row: sqlite3.Row) -> dict:
        payload = dict(row)
        payload["profile"] = json.loads(payload.pop("profile_json"))
        payload.pop("file_path", None)
        return payload

    @staticmethod
    def _job_out(row: sqlite3.Row) -> dict:
        payload = dict(row)
        payload["parameters"] = json.loads(payload.pop("parameters_json"))
        raw_result = payload.pop("result_json")
        payload["result"] = json.loads(raw_result) if raw_result else None
        return payload

    def create_dataset(
        self,
        *,
        dataset_id: str,
        project_id: str,
        user_id: str,
        name: str,
        original_filename: str,
        media_type: str,
        file_path: str,
        size_bytes: int,
        profile: dict,
    ) -> dict:
        now = self._now()
        self.execute(
            """
            INSERT INTO research_datasets (
                dataset_id, project_id, user_id, name, original_filename,
                media_type, file_path, size_bytes, row_count, column_count,
                profile_json, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?)
            """,
            (
                dataset_id,
                project_id,
                user_id,
                name,
                original_filename,
                media_type,
                file_path,
                size_bytes,
                profile["row_count"],
                profile["column_count"],
                json.dumps(profile, ensure_ascii=False),
                now,
                now,
            ),
        )
        dataset = self.get_dataset(dataset_id, user_id)
        assert dataset is not None
        return dataset

    def get_dataset(
        self,
        dataset_id: str,
        user_id: str,
        *,
        include_path: bool = False,
    ) -> dict | None:
        row = self.query_one(
            "SELECT * FROM research_datasets WHERE dataset_id = ? AND user_id = ?",
            (dataset_id, user_id),
        )
        if row is None:
            return None
        payload = self._dataset_out(row)
        if include_path:
            payload["file_path"] = row["file_path"]
        return payload

    def list_datasets(self, project_id: str, user_id: str) -> list[dict]:
        return [
            self._dataset_out(row)
            for row in self.query_all(
                """
                SELECT * FROM research_datasets
                WHERE project_id = ? AND user_id = ? AND status = 'ready'
                ORDER BY created_at DESC
                """,
                (project_id, user_id),
            )
        ]

    def create_job(
        self,
        *,
        dataset_id: str,
        project_id: str,
        user_id: str,
        analysis_type: str,
        parameters: dict,
    ) -> dict:
        now = self._now()
        job_id = str(uuid.uuid4())
        self.execute(
            """
            INSERT INTO research_analysis_jobs (
                job_id, dataset_id, project_id, user_id, analysis_type,
                parameters_json, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)
            """,
            (
                job_id,
                dataset_id,
                project_id,
                user_id,
                analysis_type,
                json.dumps(parameters, ensure_ascii=False),
                now,
                now,
            ),
        )
        job = self.get_job(job_id, user_id)
        assert job is not None
        return job

    def get_job(self, job_id: str, user_id: str | None = None) -> dict | None:
        sql = "SELECT * FROM research_analysis_jobs WHERE job_id = ?"
        params: tuple = (job_id,)
        if user_id is not None:
            sql += " AND user_id = ?"
            params += (user_id,)
        row = self.query_one(sql, params)
        return self._job_out(row) if row is not None else None

    def list_jobs(self, dataset_id: str, user_id: str) -> list[dict]:
        return [
            self._job_out(row)
            for row in self.query_all(
                """
                SELECT * FROM research_analysis_jobs
                WHERE dataset_id = ? AND user_id = ? ORDER BY created_at DESC
                """,
                (dataset_id, user_id),
            )
        ]

    def claim_job(self, job_id: str) -> dict | None:
        now = self._now()
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE research_analysis_jobs
                SET status = 'running', started_at = ?, updated_at = ?, error = NULL
                WHERE job_id = ? AND status = 'queued'
                """,
                (now, now, job_id),
            )
            if cursor.rowcount <= 0:
                return None
            row = connection.execute(
                "SELECT * FROM research_analysis_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return self._job_out(row) if row is not None else None

    def complete_job(self, job_id: str, result: dict) -> None:
        now = self._now()
        self.execute(
            """
            UPDATE research_analysis_jobs
            SET status = 'succeeded', result_json = ?, error = NULL,
                completed_at = ?, updated_at = ? WHERE job_id = ?
            """,
            (json.dumps(result, ensure_ascii=False), now, now, job_id),
        )

    def fail_job(self, job_id: str, error: str) -> None:
        now = self._now()
        self.execute(
            """
            UPDATE research_analysis_jobs
            SET status = 'failed', error = ?, completed_at = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (error[:1000], now, now, job_id),
        )

    def requeue_interrupted(self) -> list[str]:
        now = self._now()
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT job_id, status FROM research_analysis_jobs
                WHERE status IN ('queued', 'running')
                """
            ).fetchall()
            if any(row["status"] == "running" for row in rows):
                connection.execute(
                    """
                    UPDATE research_analysis_jobs
                    SET status = 'queued', started_at = NULL, updated_at = ?
                    WHERE status = 'running'
                    """,
                    (now,),
                )
        return [row["job_id"] for row in rows]
