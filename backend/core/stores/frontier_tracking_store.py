# backend/core/stores/frontier_tracking_store.py

"""提供数据持久化实现。"""

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
        """初始化 `FrontierTrackingStore` 实例。"""
        super().__init__(database_path)

    def _initialize(self) -> None:
        """初始化 `initialize` 相关数据。"""
        with closing(self._connect()) as connection, connection:
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
        """处理 `_now` 相关逻辑。"""
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _out(row: sqlite3.Row) -> dict:
        """处理 `_out` 相关逻辑。"""
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
        """创建 `job` 相关数据。

        Args:
            project_id: str => 项目 ID。
            user_id: str => 用户 ID。
            query: str => 查询文本。
            time_window_years: int => `time_window_years` 参数。
            max_results: int => `max_results` 参数。

        Returns:
            dict => 处理结果。
        """
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
        """获取 `job` 相关数据。

        Args:
            job_id: str => job ID。
            user_id: str | None => 用户 ID。

        Returns:
            dict | None => 处理结果。
        """
        sql = "SELECT * FROM research_frontier_jobs WHERE job_id = ?"
        params: tuple = (job_id,)
        if user_id is not None:
            sql += " AND user_id = ?"
            params += (user_id,)
        row = self.query_one(sql, params)
        return self._out(row) if row is not None else None

    def list_jobs(self, project_id: str, user_id: str) -> list[dict]:
        """列出 `jobs` 相关数据。

        Args:
            project_id: str => 项目 ID。
            user_id: str => 用户 ID。

        Returns:
            list[dict] => 处理结果。
        """
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
        """处理 `claim_job` 相关逻辑。

        Args:
            job_id: str => job ID。

        Returns:
            dict | None => 处理结果。
        """
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
        """处理 `complete_job` 相关逻辑。

        Args:
            job_id: str => job ID。
            result: dict => `result` 参数。
        """
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
        """处理 `fail_job` 相关逻辑。

        Args:
            job_id: str => job ID。
            error: str => `error` 参数。
        """
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
        """处理 `requeue_interrupted` 相关逻辑。"""
        now = self._now()
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT job_id, status FROM research_frontier_jobs
                WHERE status IN ('queued', 'running')
                ORDER BY created_at
                """
            ).fetchall()
            if any(row["status"] == "running" for row in rows):
                connection.execute(
                    """
                    UPDATE research_frontier_jobs
                    SET status = 'queued', started_at = NULL, updated_at = ?
                    WHERE status = 'running'
                    """,
                    (now,),
                )
        return [row["job_id"] for row in rows]
