# backend/core/stores/research_writing_store.py

"""提供数据持久化实现。"""

from __future__ import annotations

import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


class ResearchWritingStore(BaseSQLiteStore):
    """Versioned research documents and durable writing jobs."""

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        """初始化 `ResearchWritingStore` 实例。"""
        super().__init__(database_path)

    def _initialize(self) -> None:
        """初始化 `initialize` 相关数据。"""
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_documents (
                    document_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id)
                        REFERENCES research_projects(project_id) ON DELETE CASCADE,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    CHECK(document_type IN (
                        'outline', 'literature_review', 'paper', 'notes'
                    )),
                    CHECK(status IN ('active', 'archived'))
                );
                CREATE INDEX IF NOT EXISTS idx_research_documents_project
                ON research_documents(user_id, project_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS research_document_versions (
                    document_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(document_id, version),
                    FOREIGN KEY(document_id)
                        REFERENCES research_documents(document_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS research_writing_jobs (
                    job_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    instruction TEXT NOT NULL DEFAULT '',
                    source_text TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'queued',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY(document_id)
                        REFERENCES research_documents(document_id) ON DELETE CASCADE,
                    FOREIGN KEY(project_id)
                        REFERENCES research_projects(project_id) ON DELETE CASCADE,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    CHECK(operation IN (
                        'outline', 'literature_review', 'polish', 'format_check'
                    )),
                    CHECK(status IN ('queued', 'running', 'succeeded', 'failed'))
                );
                CREATE INDEX IF NOT EXISTS idx_research_writing_jobs_document
                ON research_writing_jobs(user_id, document_id, created_at DESC);
                """
            )

    @staticmethod
    def _now() -> str:
        """处理 `_now` 相关逻辑。"""
        return datetime.now(timezone.utc).isoformat()

    def create_document(
        self,
        *,
        project_id: str,
        user_id: str,
        title: str,
        document_type: str,
        content: str = "",
    ) -> dict:
        """创建 `document` 相关数据。

        Args:
            project_id: str => 项目 ID。
            user_id: str => 用户 ID。
            title: str => `title` 参数。
            document_type: str => `document_type` 参数。
            content: str => 待处理内容。

        Returns:
            dict => 处理结果。
        """
        now = self._now()
        document_id = str(uuid.uuid4())
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO research_documents (
                    document_id, project_id, user_id, title, document_type,
                    content, version, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, 'active', ?, ?)
                """,
                (
                    document_id,
                    project_id,
                    user_id,
                    title,
                    document_type,
                    content,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO research_document_versions (
                    document_id, version, content, operation, created_at
                ) VALUES (?, 1, ?, 'create', ?)
                """,
                (document_id, content, now),
            )
        document = self.get_document(document_id, user_id)
        assert document is not None
        return document

    def get_document(self, document_id: str, user_id: str) -> dict | None:
        """获取 `document` 相关数据。

        Args:
            document_id: str => document ID。
            user_id: str => 用户 ID。

        Returns:
            dict | None => 处理结果。
        """
        row = self.query_one(
            """
            SELECT * FROM research_documents
            WHERE document_id = ? AND user_id = ?
            """,
            (document_id, user_id),
        )
        return dict(row) if row is not None else None

    def list_documents(self, project_id: str, user_id: str) -> list[dict]:
        """列出 `documents` 相关数据。

        Args:
            project_id: str => 项目 ID。
            user_id: str => 用户 ID。

        Returns:
            list[dict] => 处理结果。
        """
        return [
            dict(row)
            for row in self.query_all(
                """
                SELECT * FROM research_documents
                WHERE project_id = ? AND user_id = ? AND status = 'active'
                ORDER BY updated_at DESC
                """,
                (project_id, user_id),
            )
        ]

    def list_versions(self, document_id: str, user_id: str) -> list[dict]:
        """列出 `versions` 相关数据。

        Args:
            document_id: str => document ID。
            user_id: str => 用户 ID。

        Returns:
            list[dict] => 处理结果。
        """
        if self.get_document(document_id, user_id) is None:
            return []
        return [
            dict(row)
            for row in self.query_all(
                """
                SELECT document_id, version, content, operation, created_at
                FROM research_document_versions
                WHERE document_id = ? ORDER BY version DESC
                """,
                (document_id,),
            )
        ]

    def update_document(
        self,
        document_id: str,
        user_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
    ) -> dict | None:
        """更新 `document` 相关数据。

        Args:
            document_id: str => document ID。
            user_id: str => 用户 ID。
            title: str | None => `title` 参数。
            content: str | None => 待处理内容。

        Returns:
            dict | None => 处理结果。
        """
        current = self.get_document(document_id, user_id)
        if current is None:
            return None
        next_title = current["title"] if title is None else title
        next_content = current["content"] if content is None else content
        changed_content = next_content != current["content"]
        version = int(current["version"]) + (1 if changed_content else 0)
        now = self._now()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE research_documents
                SET title = ?, content = ?, version = ?, updated_at = ?
                WHERE document_id = ? AND user_id = ?
                """,
                (next_title, next_content, version, now, document_id, user_id),
            )
            if changed_content:
                connection.execute(
                    """
                    INSERT INTO research_document_versions (
                        document_id, version, content, operation, created_at
                    ) VALUES (?, ?, ?, 'manual_edit', ?)
                    """,
                    (document_id, version, next_content, now),
                )
        return self.get_document(document_id, user_id)

    def create_job(
        self,
        *,
        document_id: str,
        project_id: str,
        user_id: str,
        operation: str,
        instruction: str,
        source_text: str,
    ) -> dict:
        """创建 `job` 相关数据。

        Args:
            document_id: str => document ID。
            project_id: str => 项目 ID。
            user_id: str => 用户 ID。
            operation: str => `operation` 参数。
            instruction: str => `instruction` 参数。
            source_text: str => `source_text` 参数。

        Returns:
            dict => 处理结果。
        """
        now = self._now()
        job_id = str(uuid.uuid4())
        self.execute(
            """
            INSERT INTO research_writing_jobs (
                job_id, document_id, project_id, user_id, operation,
                instruction, source_text, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
            """,
            (
                job_id,
                document_id,
                project_id,
                user_id,
                operation,
                instruction,
                source_text,
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
        sql = "SELECT * FROM research_writing_jobs WHERE job_id = ?"
        params: tuple = (job_id,)
        if user_id is not None:
            sql += " AND user_id = ?"
            params += (user_id,)
        row = self.query_one(sql, params)
        return dict(row) if row is not None else None

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
                UPDATE research_writing_jobs
                SET status = 'running', started_at = ?, updated_at = ?, error = NULL
                WHERE job_id = ? AND status = 'queued'
                """,
                (now, now, job_id),
            )
            if cursor.rowcount <= 0:
                return None
            row = connection.execute(
                "SELECT * FROM research_writing_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def complete_job(self, job_id: str, content: str) -> None:
        """处理 `complete_job` 相关逻辑。

        Args:
            job_id: str => job ID。
            content: str => 待处理内容。
        """
        now = self._now()
        with closing(self._connect()) as connection, connection:
            job = connection.execute(
                "SELECT * FROM research_writing_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if job is None:
                return
            document = connection.execute(
                "SELECT version FROM research_documents WHERE document_id = ?",
                (job["document_id"],),
            ).fetchone()
            if document is None:
                raise RuntimeError("research document no longer exists")
            version = int(document["version"]) + 1
            connection.execute(
                """
                UPDATE research_documents
                SET content = ?, version = ?, updated_at = ?
                WHERE document_id = ?
                """,
                (content, version, now, job["document_id"]),
            )
            connection.execute(
                """
                INSERT INTO research_document_versions (
                    document_id, version, content, operation, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (job["document_id"], version, content, job["operation"], now),
            )
            connection.execute(
                """
                UPDATE research_writing_jobs
                SET status = 'succeeded', completed_at = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (now, now, job_id),
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
            UPDATE research_writing_jobs
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
                SELECT job_id, status FROM research_writing_jobs
                WHERE status IN ('queued', 'running')
                """
            ).fetchall()
            if any(row["status"] == "running" for row in rows):
                connection.execute(
                    """
                    UPDATE research_writing_jobs
                    SET status = 'queued', started_at = NULL, updated_at = ?
                    WHERE status = 'running'
                    """,
                    (now,),
                )
        return [row["job_id"] for row in rows]
