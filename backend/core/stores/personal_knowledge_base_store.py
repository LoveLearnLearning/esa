"""Durable metadata and ordered jobs for personal knowledge bases."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


TERMINAL_JOB_STATUSES = ("succeeded", "cancelled")
MUTEX_JOB_TYPES = ("upload", "rebuild")
_ABSOLUTE_PATH = re.compile(r"(?<![\w:])/(?:[^\s'\"/:]+/)*[^\s'\":]*")
_BEARER_VALUE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_URL_CREDENTIALS = re.compile(r"(https?://)[^/@\s]+@", re.IGNORECASE)
_ERROR_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class NewPersonalKnowledgeBaseFile:
    """A validated source file that has already been durably committed."""

    file_id: str
    filename: str
    suffix: str
    media_type: str
    size_bytes: int
    sha256: str
    source_path: str
    uploaded_at: str


@dataclass(frozen=True, slots=True)
class IndexedPersonalKnowledgeBaseFile:
    """Verified derived artifacts and visible Qdrant point counts."""

    file_id: str
    docir_manifest_path: str
    chunk_manifest_path: str
    chunk_count: int
    index_count: int


class PersonalKnowledgeBaseConflict(RuntimeError):
    """The user already has an upload or rebuild mutation in flight."""


class PersonalKnowledgeBaseQuotaExceeded(RuntimeError):
    """A transaction would exceed the durable per-user quota."""


class PersonalKnowledgeBaseStore(BaseSQLiteStore):
    """Tenant-scoped access to the versioned personal-KB schema."""

    def _initialize(self) -> None:
        # This schema is intentionally migration-only. Silently creating a
        # subset here would make old production databases look healthy.
        with closing(self._connect()) as connection:
            exists = connection.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'personal_knowledge_bases'
                """
            ).fetchone()
        if exists is None:
            raise RuntimeError(
                "personal knowledge-base schema is missing; run database migrations"
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _error(value: str | None) -> str | None:
        if not value:
            return None
        safe = _BEARER_VALUE.sub("Bearer <redacted>", value)
        safe = _URL_CREDENTIALS.sub(r"\1<redacted>@", safe)
        safe = _ABSOLUTE_PATH.sub("<path>", safe)
        safe = _ERROR_CONTROLS.sub("?", safe)
        return safe[:2000]

    @staticmethod
    def _file_out(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["file_id"],
            "filename": row["filename"],
            "media_type": row["media_type"],
            "size_bytes": row["size_bytes"],
            "status": row["status"],
            "progress": row["progress"],
            "chunk_count": row["chunk_count"],
            "index_count": row["index_count"],
            "uploaded_at": row["uploaded_at"],
            "error": row["error"],
        }

    def get_snapshot(self, user_id: str) -> dict[str, Any]:
        """Read a complete polling snapshot exclusively from SQLite."""

        with closing(self._connect()) as connection:
            base = connection.execute(
                """
                SELECT * FROM personal_knowledge_bases WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            files = connection.execute(
                """
                SELECT * FROM personal_knowledge_base_files
                WHERE user_id = ? AND tombstoned_at IS NULL
                ORDER BY uploaded_at DESC, file_id
                """,
                (user_id,),
            ).fetchall()
        if base is None:
            return {
                "file_count": 0,
                "chunk_count": 0,
                "index_count": 0,
                "status": "idle",
                "progress": 0.0,
                "updated_at": None,
                "error": None,
                "files": [],
            }
        file_values = [self._file_out(row) for row in files]
        return {
            # Returning the observed list length makes the public invariant
            # explicit while aggregate repair/reconcile remains asynchronous.
            "file_count": len(file_values),
            "chunk_count": base["chunk_count"],
            "index_count": base["index_count"],
            "status": base["status"],
            "progress": base["progress"],
            "updated_at": base["updated_at"],
            "error": base["error"],
            "files": file_values,
        }

    def ensure_collection_state(self, collection_name: str) -> None:
        """Create the singleton maintenance row or validate its collection."""

        now = self._now()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO personal_knowledge_base_collection_state (
                    singleton_id, collection_name, updated_at
                ) VALUES (1, ?, ?)
                ON CONFLICT(singleton_id) DO NOTHING
                """,
                (collection_name, now),
            )
            row = connection.execute(
                """
                SELECT collection_name
                FROM personal_knowledge_base_collection_state
                WHERE singleton_id = 1
                """
            ).fetchone()
            if row is None or row["collection_name"] != collection_name:
                raise RuntimeError(
                    "personal knowledge-base collection state does not match config"
                )

    def get_collection_state(self) -> dict[str, Any] | None:
        """Return the durable collection and snapshot high-water marks."""

        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM personal_knowledge_base_collection_state
                WHERE singleton_id = 1
                """
            ).fetchone()
        return dict(row) if row is not None else None

    def get_retrieval_state(self, user_id: str) -> dict[str, Any]:
        """Read the trusted generation and live file allowlist for one query."""

        with closing(self._connect()) as connection:
            base = connection.execute(
                """
                SELECT active_generation_id, status
                FROM personal_knowledge_bases AS b
                WHERE b.user_id = ?
                  AND NOT EXISTS (
                    SELECT 1 FROM personal_knowledge_base_user_purges AS p
                    WHERE p.user_id = b.user_id
                  )
                """,
                (user_id,),
            ).fetchone()
            collection = connection.execute(
                """
                SELECT ready, error
                FROM personal_knowledge_base_collection_state
                WHERE singleton_id = 1
                """
            ).fetchone()
            files = connection.execute(
                """
                SELECT file_id, filename
                FROM personal_knowledge_base_files AS f
                WHERE f.user_id = ? AND tombstoned_at IS NULL AND status = 'ready'
                  AND NOT EXISTS (
                    SELECT 1 FROM personal_knowledge_base_user_purges AS p
                    WHERE p.user_id = f.user_id
                  )
                ORDER BY uploaded_at, file_id
                """,
                (user_id,),
            ).fetchall()
        return {
            "generation_id": (
                base["active_generation_id"] if base is not None else None
            ),
            "base_status": base["status"] if base is not None else "idle",
            "collection_ready": bool(collection["ready"]) if collection else False,
            "collection_error": collection["error"] if collection else None,
            "files": {row["file_id"]: row["filename"] for row in files},
        }

    def mark_collection_ready(self, *, ready: bool, error: str | None = None) -> None:
        """Publish startup recovery readiness for retrieval and operations."""

        now = self._now()
        self.execute(
            """
            UPDATE personal_knowledge_base_collection_state
            SET ready = ?, error = ?, updated_at = ?
            WHERE singleton_id = 1
            """,
            (int(ready), self._error(error), now),
        )

    def mark_collection_rebuilt(self) -> None:
        """Publish a verified authority rebuild and require a fresh snapshot."""

        now = self._now()
        self.execute(
            """
            UPDATE personal_knowledge_base_collection_state
            SET ready = 1, snapshot_dirty = 1, error = NULL, updated_at = ?
            WHERE singleton_id = 1
            """,
            (now,),
        )

    def list_collection_rebuild_authority(self) -> list[dict[str, Any]]:
        """Return committed live files grouped by their active generation."""

        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT b.user_id, b.active_generation_id AS generation_id,
                       g.embedding_fingerprint, g.chunk_fingerprint,
                       g.index_fingerprint, g.locator_schema_version,
                       f.file_id, f.filename, f.media_type, f.sha256,
                       f.source_path, f.ingestion_revision, f.index_count
                FROM personal_knowledge_bases AS b
                JOIN personal_knowledge_base_generations AS g
                  ON g.user_id = b.user_id
                 AND g.generation_id = b.active_generation_id
                JOIN personal_knowledge_base_files AS f
                  ON f.user_id = b.user_id
                WHERE f.tombstoned_at IS NULL
                  AND f.status = 'ready'
                  AND f.indexed_revision IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM personal_knowledge_base_user_purges AS p
                    WHERE p.user_id = b.user_id
                  )
                ORDER BY b.user_id, f.uploaded_at, f.file_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_retained_file_ids(self) -> set[str]:
        """Return source/artifact directories still owned by durable metadata."""

        return {
            str(row["file_id"])
            for row in self.query_all(
                """
                SELECT file_id FROM personal_knowledge_base_files
                WHERE cleanup_completed_at IS NULL
                """
            )
        }

    def clear_upload_reservations(self) -> int:
        """Release upload leases left by a previous single-writer process."""

        return self.execute("DELETE FROM personal_knowledge_base_upload_reservations")

    def reserve_upload_capacity(
        self,
        *,
        user_id: str,
        reserved_files: int,
        reserved_bytes: int,
        max_user_files: int,
        max_user_bytes: int,
    ) -> str:
        """Atomically reserve quota before bytes reach durable storage."""

        if reserved_files <= 0 or reserved_bytes <= 0:
            raise ValueError("upload reservation must be positive")
        reservation_id = str(uuid.uuid4())
        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._ensure_base(connection, user_id, now)
                self._ensure_not_purging(connection, user_id)
                if self._has_mutex_job(connection, user_id):
                    raise PersonalKnowledgeBaseConflict(
                        "personal knowledge-base upload or rebuild already in progress"
                    )
                usage = connection.execute(
                    """
                    SELECT COUNT(*) AS file_count,
                           COALESCE(SUM(size_bytes), 0) AS size_bytes
                    FROM personal_knowledge_base_files
                    WHERE user_id = ? AND tombstoned_at IS NULL
                    """,
                    (user_id,),
                ).fetchone()
                reserved = connection.execute(
                    """
                    SELECT COALESCE(SUM(reserved_files), 0) AS file_count,
                           COALESCE(SUM(reserved_bytes), 0) AS size_bytes
                    FROM personal_knowledge_base_upload_reservations
                    WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()
                if (
                    int(usage["file_count"])
                    + int(reserved["file_count"])
                    + reserved_files
                    > max_user_files
                    or int(usage["size_bytes"])
                    + int(reserved["size_bytes"])
                    + reserved_bytes
                    > max_user_bytes
                ):
                    raise PersonalKnowledgeBaseQuotaExceeded(
                        "personal knowledge-base user quota exceeded"
                    )
                connection.execute(
                    """
                    INSERT INTO personal_knowledge_base_upload_reservations (
                        reservation_id, user_id, reserved_files,
                        reserved_bytes, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        reservation_id, user_id, reserved_files,
                        reserved_bytes, now,
                    ),
                )
                connection.commit()
                return reservation_id
            except BaseException:
                connection.rollback()
                raise

    def release_upload_reservation(
        self, *, user_id: str, reservation_id: str
    ) -> bool:
        return self.execute(
            """
            DELETE FROM personal_knowledge_base_upload_reservations
            WHERE user_id = ? AND reservation_id = ?
            """,
            (user_id, reservation_id),
        ) == 1

    def get_operational_metrics(self) -> dict[str, Any]:
        """Return lightweight queue/readiness counters without touching Qdrant."""

        with closing(self._connect()) as connection:
            job_rows = connection.execute(
                """
                SELECT status, stage, COUNT(*) AS count
                FROM personal_knowledge_base_jobs
                GROUP BY status, stage
                """
            ).fetchall()
            stage_duration_rows = connection.execute(
                """
                SELECT stage, COUNT(*) AS samples,
                       AVG(COALESCE(
                           duration_seconds,
                           MAX(0.0, (julianday('now') - julianday(started_at)) * 86400.0)
                       )) AS average_seconds,
                       MAX(COALESCE(
                           duration_seconds,
                           MAX(0.0, (julianday('now') - julianday(started_at)) * 86400.0)
                       )) AS maximum_seconds
                FROM personal_knowledge_base_job_stage_events
                GROUP BY stage
                """
            ).fetchall()
            pending_generations = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM personal_knowledge_base_generations
                    WHERE status IN ('staging', 'retired')
                      AND index_count > 0
                    """
                ).fetchone()[0]
            )
            pending_deletions = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM personal_knowledge_base_files
                    WHERE tombstoned_at IS NOT NULL
                      AND cleanup_completed_at IS NULL
                    """
                ).fetchone()[0]
            )
            state = connection.execute(
                """
                SELECT ready, snapshot_dirty, qdrant_mutation_seq,
                       snapshot_mutation_seq, error
                FROM personal_knowledge_base_collection_state
                WHERE singleton_id = 1
                """
            ).fetchone()
        by_status: dict[str, int] = {}
        by_stage: dict[str, int] = {}
        for row in job_rows:
            by_status[row["status"]] = by_status.get(row["status"], 0) + int(
                row["count"]
            )
            by_stage[row["stage"]] = by_stage.get(row["stage"], 0) + int(
                row["count"]
            )
        stage_durations = {
            str(row["stage"]): {
                "samples": int(row["samples"]),
                "average_seconds": round(float(row["average_seconds"]), 3),
                "maximum_seconds": round(float(row["maximum_seconds"]), 3),
            }
            for row in stage_duration_rows
        }
        return {
            "jobs_by_status": by_status,
            "jobs_by_stage": by_stage,
            "stage_duration_seconds": stage_durations,
            "queue_length": by_status.get("queued", 0),
            "active_jobs": by_status.get("running", 0),
            "successful_jobs": by_status.get("succeeded", 0),
            "failed_jobs": by_status.get("failed", 0),
            "pending_generation_cleanup": pending_generations,
            "pending_file_cleanup": pending_deletions,
            "collection_ready": bool(state["ready"]) if state else False,
            "snapshot_dirty": bool(state["snapshot_dirty"]) if state else False,
            "qdrant_mutation_seq": int(state["qdrant_mutation_seq"]) if state else 0,
            "snapshot_mutation_seq": int(state["snapshot_mutation_seq"]) if state else 0,
            "error": state["error"] if state else None,
        }

    def list_applied_mutations_after(
        self, qdrant_mutation_seq: int
    ) -> list[dict[str, Any]]:
        """Read the immutable ordered journal tail after a restore cursor."""

        rows = self.query_all(
            """
            SELECT mutation_id, user_id, target_revision, operation,
                   payload_json, qdrant_mutation_seq, applied_at
            FROM personal_knowledge_base_mutations
            WHERE status = 'applied' AND qdrant_mutation_seq > ?
            UNION ALL
            SELECT purge_id AS mutation_id, user_id, 0 AS target_revision,
                   'delete_user' AS operation, '{}' AS payload_json,
                   qdrant_mutation_seq, applied_at
            FROM personal_knowledge_base_user_purges
            WHERE status IN ('applied', 'completed')
              AND qdrant_mutation_seq > ?
            ORDER BY qdrant_mutation_seq
            """,
            (qdrant_mutation_seq, qdrant_mutation_seq),
        )
        values = []
        for row in rows:
            value = dict(row)
            value["payload"] = json.loads(value.pop("payload_json"))
            values.append(value)
        return values

    def invalidate_restorable_snapshot(self, snapshot_id: str) -> bool:
        """Exclude a corrupt or incompatible snapshot from future restores."""

        return self.execute(
            """
            UPDATE personal_knowledge_base_snapshots
            SET status = 'invalid'
            WHERE snapshot_id = ? AND status = 'valid'
            """,
            (snapshot_id,),
        ) == 1

    def begin_snapshot(
        self,
        *,
        snapshot_id: str,
        snapshot_path: str,
        collection_name: str,
        point_count: int,
        qdrant_mutation_seq: int,
        embedding_fingerprint: str,
        index_fingerprint: str,
        locator_schema_version: str,
    ) -> None:
        """Persist snapshot intent before copying its bytes to durable storage."""

        if point_count < 0 or qdrant_mutation_seq < 0:
            raise ValueError("snapshot counts cannot be negative")
        now = self._now()
        with closing(self._connect()) as connection, connection:
            state = connection.execute(
                """
                SELECT collection_name, qdrant_mutation_seq
                FROM personal_knowledge_base_collection_state
                WHERE singleton_id = 1
                """
            ).fetchone()
            if (
                state is None
                or state["collection_name"] != collection_name
                or int(state["qdrant_mutation_seq"]) < qdrant_mutation_seq
            ):
                raise RuntimeError("snapshot sequence is not commit eligible")
            connection.execute(
                """
                INSERT INTO personal_knowledge_base_snapshots (
                    snapshot_id, snapshot_path, sha256, collection_name,
                    point_count, qdrant_mutation_seq, embedding_fingerprint,
                    index_fingerprint, locator_schema_version, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'creating', ?)
                """,
                (
                    snapshot_id, snapshot_path, "0" * 64, collection_name,
                    point_count, qdrant_mutation_seq, embedding_fingerprint,
                    index_fingerprint, locator_schema_version, now,
                ),
            )

    def commit_snapshot(self, *, snapshot_id: str, sha256: str) -> None:
        """Validate one copied snapshot and advance the covered sequence."""

        if len(sha256) != 64:
            raise ValueError("snapshot SHA-256 must contain 64 hexadecimal digits")
        int(sha256, 16)
        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """
                    UPDATE personal_knowledge_base_snapshots
                    SET sha256 = ?, status = 'valid', verified_at = ?
                    WHERE snapshot_id = ? AND status = 'creating'
                    RETURNING qdrant_mutation_seq, collection_name
                    """,
                    (sha256, now, snapshot_id),
                ).fetchone()
                if row is None:
                    raise RuntimeError("snapshot is no longer commit eligible")
                updated = connection.execute(
                    """
                    UPDATE personal_knowledge_base_collection_state
                    SET snapshot_mutation_seq = MAX(
                            snapshot_mutation_seq, ?
                        ),
                        snapshot_dirty = CASE
                            WHEN qdrant_mutation_seq <= ? THEN 0 ELSE 1
                        END,
                        ready = 1, error = NULL, updated_at = ?
                    WHERE singleton_id = 1 AND collection_name = ?
                    """,
                    (
                        int(row["qdrant_mutation_seq"]),
                        int(row["qdrant_mutation_seq"]),
                        now,
                        row["collection_name"],
                    ),
                ).rowcount
                if updated != 1:
                    raise RuntimeError("snapshot collection state is inconsistent")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def invalidate_snapshot(self, *, snapshot_id: str, error: str) -> None:
        """Make an incomplete snapshot ineligible for startup restore."""

        now = self._now()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE personal_knowledge_base_snapshots
                SET status = 'invalid'
                WHERE snapshot_id = ? AND status = 'creating'
                """,
                (snapshot_id,),
            )
            connection.execute(
                """
                UPDATE personal_knowledge_base_collection_state
                SET error = ?, snapshot_dirty = 1, updated_at = ?
                WHERE singleton_id = 1
                """,
                (self._error(error), now),
            )

    def list_valid_snapshots(self) -> list[dict[str, Any]]:
        """List restorable snapshots newest sequence first."""

        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM personal_knowledge_base_snapshots
                WHERE status = 'valid'
                ORDER BY qdrant_mutation_seq DESC, created_at DESC, snapshot_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_snapshot_deleted(self, snapshot_id: str) -> bool:
        """Retire one durable snapshot only after its files were removed."""

        return self.execute(
            """
            UPDATE personal_knowledge_base_snapshots
            SET status = 'deleted'
            WHERE snapshot_id = ? AND status IN ('valid', 'invalid')
            """,
            (snapshot_id,),
        ) == 1

    def list_deletions_covered_by_snapshot(
        self, qdrant_mutation_seq: int
    ) -> list[dict[str, Any]]:
        """Find tombstones whose verified deletion is in a clean snapshot."""

        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT f.user_id, f.file_id, m.qdrant_mutation_seq
                FROM personal_knowledge_base_files AS f
                JOIN personal_knowledge_base_mutations AS m
                  ON m.user_id = f.user_id
                 AND m.operation = 'delete_file'
                 AND json_extract(m.payload_json, '$.file_id') = f.file_id
                WHERE f.tombstoned_at IS NOT NULL
                  AND f.cleanup_completed_at IS NULL
                  AND m.status = 'applied'
                  AND m.qdrant_mutation_seq <= ?
                ORDER BY m.qdrant_mutation_seq, f.user_id, f.file_id
                """,
                (qdrant_mutation_seq,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_user_purges_covered_by_snapshot(
        self, qdrant_mutation_seq: int
    ) -> list[dict[str, Any]]:
        """Return tenant-wide deletions that this snapshot must prove clean."""

        rows = self.query_all(
            """
            SELECT purge_id, user_id, qdrant_mutation_seq
            FROM personal_knowledge_base_user_purges
            WHERE status = 'applied' AND qdrant_mutation_seq <= ?
            ORDER BY qdrant_mutation_seq, user_id
            """,
            (qdrant_mutation_seq,),
        )
        return [dict(row) for row in rows]

    def begin_user_purge(self, user_id: str) -> dict[str, Any]:
        """Freeze one tenant and durably capture every owned file identifier."""

        if not user_id:
            raise ValueError("user_id cannot be blank")
        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    """
                    SELECT * FROM personal_knowledge_base_user_purges
                    WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()
                if existing is not None:
                    if existing["status"] == "failed":
                        connection.execute(
                            """
                            UPDATE personal_knowledge_base_user_purges
                            SET status = 'pending', error = NULL, updated_at = ?
                            WHERE purge_id = ?
                            """,
                            (now, existing["purge_id"]),
                        )
                        existing = connection.execute(
                            """
                            SELECT * FROM personal_knowledge_base_user_purges
                            WHERE purge_id = ?
                            """,
                            (existing["purge_id"],),
                        ).fetchone()
                    connection.commit()
                    value = dict(existing)
                    value["file_ids"] = json.loads(value.pop("file_ids_json"))
                    return value
                user = connection.execute(
                    "SELECT 1 FROM users WHERE id = ?", (user_id,)
                ).fetchone()
                if user is None:
                    raise ValueError("user does not exist")
                active = connection.execute(
                    """
                    SELECT 1 FROM personal_knowledge_base_jobs
                    WHERE user_id = ?
                      AND status IN ('queued', 'running', 'cancel_requested')
                    LIMIT 1
                    """,
                    (user_id,),
                ).fetchone()
                if active is not None:
                    raise PersonalKnowledgeBaseConflict(
                        "personal knowledge-base jobs must be quiesced before user purge"
                    )
                file_ids = [
                    str(row["file_id"])
                    for row in connection.execute(
                        """
                        SELECT file_id FROM personal_knowledge_base_files
                        WHERE user_id = ? ORDER BY uploaded_at, file_id
                        """,
                        (user_id,),
                    ).fetchall()
                ]
                purge_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO personal_knowledge_base_user_purges (
                        purge_id, user_id, status, file_ids_json,
                        created_at, updated_at
                    ) VALUES (?, ?, 'pending', ?, ?, ?)
                    """,
                    (purge_id, user_id, json.dumps(file_ids), now, now),
                )
                connection.commit()
                return {
                    "purge_id": purge_id,
                    "user_id": user_id,
                    "status": "pending",
                    "file_ids": file_ids,
                    "qdrant_mutation_seq": None,
                    "error": None,
                    "created_at": now,
                    "applied_at": None,
                    "cleanup_completed_at": None,
                    "updated_at": now,
                }
            except BaseException:
                connection.rollback()
                raise

    def get_user_purge(self, user_id: str) -> dict[str, Any] | None:
        row = self.query_one(
            """
            SELECT * FROM personal_knowledge_base_user_purges
            WHERE user_id = ?
            """,
            (user_id,),
        )
        if row is None:
            return None
        value = dict(row)
        value["file_ids"] = json.loads(value.pop("file_ids_json"))
        return value

    def mark_user_purge_applying(self, *, purge_id: str, user_id: str) -> bool:
        """Move a frozen tenant purge to its replay-safe external phase."""

        return self.execute(
            """
            UPDATE personal_knowledge_base_user_purges
            SET status = 'applying', error = NULL, updated_at = ?
            WHERE purge_id = ? AND user_id = ?
              AND status IN ('pending', 'applying')
            """,
            (self._now(), purge_id, user_id),
        ) == 1

    def commit_user_purge(self, *, purge_id: str, user_id: str) -> int:
        """Commit verified tenant deletion and remove all user-scoped KB rows."""

        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                purge = connection.execute(
                    """
                    SELECT status, qdrant_mutation_seq
                    FROM personal_knowledge_base_user_purges
                    WHERE purge_id = ? AND user_id = ?
                    """,
                    (purge_id, user_id),
                ).fetchone()
                if purge is None:
                    raise RuntimeError("personal user purge record is missing")
                if purge["status"] in ("applied", "completed"):
                    connection.commit()
                    return int(purge["qdrant_mutation_seq"])
                if purge["status"] != "applying":
                    raise RuntimeError("personal user purge is not commit eligible")
                state = connection.execute(
                    """
                    UPDATE personal_knowledge_base_collection_state
                    SET qdrant_mutation_seq = qdrant_mutation_seq + 1,
                        snapshot_dirty = 1, updated_at = ?
                    WHERE singleton_id = 1
                    RETURNING qdrant_mutation_seq
                    """,
                    (now,),
                ).fetchone()
                if state is None:
                    raise RuntimeError("personal collection state is missing")
                sequence = int(state[0])
                connection.execute(
                    """
                    UPDATE personal_knowledge_base_user_purges
                    SET status = 'applied', qdrant_mutation_seq = ?,
                        applied_at = ?, updated_at = ?
                    WHERE purge_id = ? AND user_id = ? AND status = 'applying'
                    """,
                    (sequence, now, now, purge_id, user_id),
                )
                # The purge record intentionally has no FK and survives a later
                # users-row deletion. Everything below is derived/user-owned KB
                # state and is safe to remove only after Qdrant verification.
                for table in (
                    "personal_knowledge_base_upload_reservations",
                    "personal_knowledge_base_jobs",
                    "personal_knowledge_base_mutations",
                    "personal_knowledge_base_files",
                    "personal_knowledge_bases",
                    "personal_knowledge_base_generations",
                ):
                    connection.execute(
                        f"DELETE FROM {table} WHERE user_id = ?", (user_id,)
                    )
                connection.commit()
                return sequence
            except BaseException:
                connection.rollback()
                raise

    def fail_user_purge(
        self, *, purge_id: str, user_id: str, error: str
    ) -> None:
        self.execute(
            """
            UPDATE personal_knowledge_base_user_purges
            SET status = 'failed', error = ?, updated_at = ?
            WHERE purge_id = ? AND user_id = ? AND status != 'completed'
            """,
            (self._error(error), self._now(), purge_id, user_id),
        )

    def complete_user_purge(
        self, *, purge_id: str, qdrant_mutation_seq: int
    ) -> bool:
        """Seal a purge only after every older restorable snapshot is gone."""

        now = self._now()
        with closing(self._connect()) as connection, connection:
            older = connection.execute(
                """
                SELECT 1 FROM personal_knowledge_base_snapshots
                WHERE status = 'valid' AND qdrant_mutation_seq < ? LIMIT 1
                """,
                (qdrant_mutation_seq,),
            ).fetchone()
            if older is not None:
                return False
            return connection.execute(
                """
                UPDATE personal_knowledge_base_user_purges
                SET status = 'completed', cleanup_completed_at = ?, updated_at = ?
                WHERE purge_id = ? AND status = 'applied'
                  AND qdrant_mutation_seq = ?
                """,
                (now, now, purge_id, qdrant_mutation_seq),
            ).rowcount == 1

    def complete_deletion_cleanup(
        self, *, user_id: str, file_id: str, qdrant_mutation_seq: int
    ) -> bool:
        """Seal privacy cleanup after all older valid snapshots were purged."""

        now = self._now()
        with closing(self._connect()) as connection, connection:
            older = connection.execute(
                """
                SELECT 1 FROM personal_knowledge_base_snapshots
                WHERE status = 'valid' AND qdrant_mutation_seq < ?
                LIMIT 1
                """,
                (qdrant_mutation_seq,),
            ).fetchone()
            if older is not None:
                return False
            return connection.execute(
                """
                UPDATE personal_knowledge_base_files
                SET cleanup_completed_at = ?, updated_at = ?
                WHERE user_id = ? AND file_id = ?
                  AND tombstoned_at IS NOT NULL
                  AND cleanup_completed_at IS NULL
                """,
                (now, now, user_id, file_id),
            ).rowcount == 1

    def cleanup_audit_records(self, *, completed_before: str) -> dict[str, int]:
        """Prune completed derived metadata without shortening replay history.

        Failed jobs and every mutation-journal row are deliberately retained:
        either can still be required for explicit retry or snapshot replay.
        """

        # Validate the operator-supplied boundary before opening a write txn.
        datetime.fromisoformat(completed_before.replace("Z", "+00:00"))
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                jobs = connection.execute(
                    """
                    DELETE FROM personal_knowledge_base_jobs
                    WHERE status IN ('succeeded', 'cancelled')
                      AND completed_at IS NOT NULL AND completed_at < ?
                    """,
                    (completed_before,),
                ).rowcount
                files = connection.execute(
                    """
                    DELETE FROM personal_knowledge_base_files
                    WHERE cleanup_completed_at IS NOT NULL
                      AND cleanup_completed_at < ?
                    """,
                    (completed_before,),
                ).rowcount
                generations = connection.execute(
                    """
                    DELETE FROM personal_knowledge_base_generations
                    WHERE status = 'retired' AND index_count = 0
                      AND retired_at IS NOT NULL AND retired_at < ?
                      AND generation_id NOT IN (
                          SELECT active_generation_id
                          FROM personal_knowledge_bases
                          WHERE active_generation_id IS NOT NULL
                          UNION
                          SELECT building_generation_id
                          FROM personal_knowledge_bases
                          WHERE building_generation_id IS NOT NULL
                      )
                    """,
                    (completed_before,),
                ).rowcount
                snapshots = connection.execute(
                    """
                    DELETE FROM personal_knowledge_base_snapshots
                    WHERE status IN ('deleted', 'invalid') AND created_at < ?
                    """,
                    (completed_before,),
                ).rowcount
                connection.commit()
                return {
                    "jobs": jobs,
                    "files": files,
                    "generations": generations,
                    "snapshots": snapshots,
                }
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _ensure_base(connection: sqlite3.Connection, user_id: str, now: str) -> None:
        connection.execute(
            """
            INSERT INTO personal_knowledge_bases (
                user_id, status, progress, created_at, updated_at
            ) VALUES (?, 'idle', 0.0, ?, ?)
            ON CONFLICT(user_id) DO NOTHING
            """,
            (user_id, now, now),
        )

    @staticmethod
    def _has_mutex_job(connection: sqlite3.Connection, user_id: str) -> bool:
        return connection.execute(
            """
            SELECT 1 FROM personal_knowledge_base_jobs
            WHERE user_id = ?
              AND job_type IN ('upload', 'rebuild')
              AND status IN ('queued', 'running', 'cancel_requested')
            LIMIT 1
            """,
            (user_id,),
        ).fetchone() is not None

    @staticmethod
    def _ensure_not_purging(
        connection: sqlite3.Connection, user_id: str
    ) -> None:
        if connection.execute(
            """
            SELECT 1 FROM personal_knowledge_base_user_purges
            WHERE user_id = ? LIMIT 1
            """,
            (user_id,),
        ).fetchone() is not None:
            raise PersonalKnowledgeBaseConflict(
                "personal knowledge-base user data has been scheduled for purge"
            )

    def create_upload(
        self,
        *,
        user_id: str,
        files: Iterable[NewPersonalKnowledgeBaseFile],
        max_user_bytes: int | None = None,
        max_user_files: int | None = None,
        reservation_id: str | None = None,
    ) -> tuple[list[str], str | None]:
        """Atomically deduplicate files, increment one revision and queue a job."""

        candidates = list(files)
        if not candidates:
            return [], None
        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._ensure_base(connection, user_id, now)
                self._ensure_not_purging(connection, user_id)
                if reservation_id is not None:
                    reservation = connection.execute(
                        """
                        SELECT 1
                        FROM personal_knowledge_base_upload_reservations
                        WHERE reservation_id = ? AND user_id = ?
                        """,
                        (reservation_id, user_id),
                    ).fetchone()
                    if reservation is None:
                        raise RuntimeError("upload quota reservation is missing")
                if self._has_mutex_job(connection, user_id):
                    raise PersonalKnowledgeBaseConflict(
                        "personal knowledge-base upload or rebuild already in progress"
                    )
                existing = {
                    row["sha256"]: row["file_id"]
                    for row in connection.execute(
                        """
                        SELECT file_id, sha256
                        FROM personal_knowledge_base_files
                        WHERE user_id = ? AND tombstoned_at IS NULL
                        """,
                        (user_id,),
                    ).fetchall()
                }
                unique: list[NewPersonalKnowledgeBaseFile] = []
                ids: list[str] = []
                for item in candidates:
                    duplicate_id = existing.get(item.sha256)
                    if duplicate_id is not None:
                        ids.append(duplicate_id)
                        continue
                    existing[item.sha256] = item.file_id
                    unique.append(item)
                    ids.append(item.file_id)
                if not unique:
                    if reservation_id is not None:
                        connection.execute(
                            """
                            DELETE FROM personal_knowledge_base_upload_reservations
                            WHERE reservation_id = ? AND user_id = ?
                            """,
                            (reservation_id, user_id),
                        )
                    connection.commit()
                    return ids, None

                usage = connection.execute(
                    """
                    SELECT COUNT(*) AS file_count,
                           COALESCE(SUM(size_bytes), 0) AS size_bytes
                    FROM personal_knowledge_base_files
                    WHERE user_id = ? AND tombstoned_at IS NULL
                    """,
                    (user_id,),
                ).fetchone()
                resulting_files = int(usage["file_count"]) + len(unique)
                resulting_bytes = int(usage["size_bytes"]) + sum(
                    item.size_bytes for item in unique
                )
                reserved = connection.execute(
                    """
                    SELECT COALESCE(SUM(reserved_files), 0) AS file_count,
                           COALESCE(SUM(reserved_bytes), 0) AS size_bytes
                    FROM personal_knowledge_base_upload_reservations
                    WHERE user_id = ? AND reservation_id != COALESCE(?, '')
                    """,
                    (user_id, reservation_id),
                ).fetchone()
                resulting_files += int(reserved["file_count"])
                resulting_bytes += int(reserved["size_bytes"])
                if (
                    max_user_files is not None
                    and resulting_files > max_user_files
                ) or (
                    max_user_bytes is not None
                    and resulting_bytes > max_user_bytes
                ):
                    raise PersonalKnowledgeBaseQuotaExceeded(
                        "personal knowledge-base user quota exceeded"
                    )

                revision = int(
                    connection.execute(
                        """
                        UPDATE personal_knowledge_bases
                        SET desired_revision = desired_revision + 1,
                            status = 'queued', progress = 0.0, error = NULL,
                            updated_at = ?
                        WHERE user_id = ?
                        RETURNING desired_revision
                        """,
                        (now, user_id),
                    ).fetchone()[0]
                )
                for item in unique:
                    connection.execute(
                        """
                        INSERT INTO personal_knowledge_base_files (
                            file_id, user_id, filename, suffix, media_type,
                            size_bytes, sha256, source_path, ingestion_revision,
                            status, progress, uploaded_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0.0, ?, ?)
                        """,
                        (
                            item.file_id, user_id, item.filename, item.suffix,
                            item.media_type, item.size_bytes, item.sha256,
                            item.source_path, revision, item.uploaded_at, now,
                        ),
                    )
                job_id = str(uuid.uuid4())
                new_ids = [item.file_id for item in unique]
                connection.execute(
                    """
                    INSERT INTO personal_knowledge_base_jobs (
                        job_id, user_id, job_type, status, progress,
                        target_revision, payload_json, created_at, updated_at
                    ) VALUES (?, ?, 'upload', 'queued', 0.0, ?, ?, ?, ?)
                    """,
                    (
                        job_id, user_id, revision,
                        json.dumps({"file_ids": new_ids}), now, now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO personal_knowledge_base_mutations (
                        mutation_id, user_id, target_revision, operation,
                        payload_json, status, created_at, updated_at
                    ) VALUES (?, ?, ?, 'publish_file', ?, 'pending', ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), user_id, revision,
                        json.dumps({"file_ids": new_ids}), now, now,
                    ),
                )
                connection.execute(
                    """
                    UPDATE personal_knowledge_bases
                    SET file_count = (
                        SELECT COUNT(*) FROM personal_knowledge_base_files
                        WHERE user_id = ? AND tombstoned_at IS NULL
                    )
                    WHERE user_id = ?
                    """,
                    (user_id, user_id),
                )
                if reservation_id is not None:
                    connection.execute(
                        """
                        DELETE FROM personal_knowledge_base_upload_reservations
                        WHERE reservation_id = ? AND user_id = ?
                        """,
                        (reservation_id, user_id),
                    )
                connection.commit()
                return ids, job_id
            except BaseException:
                connection.rollback()
                raise

    def queue_rebuild(self, user_id: str) -> str | None:
        """Queue a full rebuild; return ``None`` for an empty knowledge base."""

        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._ensure_base(connection, user_id, now)
                self._ensure_not_purging(connection, user_id)
                if self._has_mutex_job(connection, user_id):
                    raise PersonalKnowledgeBaseConflict(
                        "personal knowledge-base upload or rebuild already in progress"
                    )
                file_ids = [
                    row[0]
                    for row in connection.execute(
                        """
                        SELECT file_id FROM personal_knowledge_base_files
                        WHERE user_id = ? AND tombstoned_at IS NULL
                        ORDER BY uploaded_at, file_id
                        """,
                        (user_id,),
                    ).fetchall()
                ]
                if not file_ids:
                    connection.commit()
                    return None
                revision = connection.execute(
                    """
                    UPDATE personal_knowledge_bases
                    SET desired_revision = desired_revision + 1,
                        status = 'queued', progress = 0.0, error = NULL,
                        updated_at = ?
                    WHERE user_id = ?
                    RETURNING desired_revision
                    """,
                    (now, user_id),
                ).fetchone()[0]
                job_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO personal_knowledge_base_jobs (
                        job_id, user_id, job_type, target_revision,
                        payload_json, created_at, updated_at
                    ) VALUES (?, ?, 'rebuild', ?, ?, ?, ?)
                    """,
                    (job_id, user_id, revision, json.dumps({"file_ids": file_ids}), now, now),
                )
                connection.execute(
                    """
                    INSERT INTO personal_knowledge_base_mutations (
                        mutation_id, user_id, target_revision, operation,
                        payload_json, status, created_at, updated_at
                    ) VALUES (?, ?, ?, 'activate_generation', ?, 'pending', ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), user_id, revision,
                        json.dumps({"file_ids": file_ids}), now, now,
                    ),
                )
                connection.commit()
                return job_id
            except BaseException:
                connection.rollback()
                raise

    def tombstone_file(self, *, user_id: str, file_id: str) -> bool:
        """Hide an owned file synchronously and durably queue cleanup."""

        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._ensure_not_purging(connection, user_id)
                row = connection.execute(
                    """
                    SELECT tombstoned_at, cleanup_completed_at
                    FROM personal_knowledge_base_files
                    WHERE user_id = ? AND file_id = ?
                    """,
                    (user_id, file_id),
                ).fetchone()
                if row is None or row["cleanup_completed_at"] is not None:
                    connection.commit()
                    return False
                if row["tombstoned_at"] is not None:
                    connection.commit()
                    return True
                revision = connection.execute(
                    """
                    UPDATE personal_knowledge_bases
                    SET desired_revision = desired_revision + 1,
                        updated_at = ?
                    WHERE user_id = ?
                    RETURNING desired_revision
                    """,
                    (now, user_id),
                ).fetchone()
                if revision is None:
                    connection.commit()
                    return False
                target_revision = revision[0]
                connection.execute(
                    """
                    UPDATE personal_knowledge_base_files
                    SET tombstoned_at = ?, updated_at = ?
                    WHERE user_id = ? AND file_id = ?
                    """,
                    (now, now, user_id, file_id),
                )
                job_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO personal_knowledge_base_jobs (
                        job_id, user_id, job_type, target_revision,
                        payload_json, created_at, updated_at
                    ) VALUES (?, ?, 'delete', ?, ?, ?, ?)
                    """,
                    (
                        job_id, user_id, target_revision,
                        json.dumps({"file_id": file_id}), now, now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO personal_knowledge_base_mutations (
                        mutation_id, user_id, target_revision, operation,
                        payload_json, status, created_at, updated_at
                    ) VALUES (?, ?, ?, 'delete_file', ?, 'pending', ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), user_id, target_revision,
                        json.dumps({"file_id": file_id}), now, now,
                    ),
                )
                connection.execute(
                    """
                    UPDATE personal_knowledge_bases
                    SET file_count = file_count - 1,
                        status = CASE WHEN file_count = 1 THEN 'idle' ELSE status END,
                        progress = CASE WHEN file_count = 1 THEN 0.0 ELSE progress END,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (now, user_id),
                )
                connection.commit()
                return True
            except BaseException:
                connection.rollback()
                raise

    def recover_running_jobs(self) -> int:
        """Return interrupted work to the durable queue after process restart."""

        now = self._now()
        return self.execute(
            """
            UPDATE personal_knowledge_base_jobs
            SET status = 'queued', stage = 'queued', started_at = NULL,
                updated_at = ?
            WHERE status = 'running'
            """,
            (now,),
        )

    def has_revision_lag(self) -> bool:
        """Return whether durable user intent is not fully reflected in Qdrant."""

        row = self.query_one(
            """
            SELECT 1
            FROM personal_knowledge_bases AS b
            WHERE b.desired_revision != b.indexed_revision
               OR EXISTS (
                    SELECT 1 FROM personal_knowledge_base_jobs AS j
                    WHERE j.user_id = b.user_id
                      AND j.job_type IN ('upload', 'rebuild', 'delete')
                      AND j.status IN ('queued', 'running', 'failed')
               )
            LIMIT 1
            """
        )
        return row is not None

    def get_job_files(
        self, *, user_id: str, file_ids: Iterable[str]
    ) -> list[dict[str, Any]]:
        """Return only owned live files in the caller's stable requested order."""

        requested = list(dict.fromkeys(file_ids))
        if not requested:
            return []
        placeholders = ",".join("?" for _ in requested)
        rows = self.query_all(
            f"""
            SELECT * FROM personal_knowledge_base_files
            WHERE user_id = ? AND tombstoned_at IS NULL
              AND file_id IN ({placeholders})
            """,
            (user_id, *requested),
        )
        by_id = {row["file_id"]: dict(row) for row in rows}
        return [by_id[file_id] for file_id in requested if file_id in by_id]

    def get_live_file(self, *, user_id: str, file_id: str) -> dict[str, Any] | None:
        """Return an owned, visible file or ``None`` without leaking tenancy.

        A pending or completed user purge is a permanent deny marker.  Content
        reads therefore fail closed as soon as purge begins, even before its
        asynchronous filesystem cleanup commits.
        """

        row = self.query_one(
            """
            SELECT f.*
            FROM personal_knowledge_base_files AS f
            WHERE f.user_id = ? AND f.file_id = ?
              AND f.tombstoned_at IS NULL
              AND NOT EXISTS (
                    SELECT 1 FROM personal_knowledge_base_user_purges AS p
                    WHERE p.user_id = f.user_id
              )
            """,
            (user_id, file_id),
        )
        return dict(row) if row is not None else None

    def get_tombstoned_file(
        self, *, user_id: str, file_id: str
    ) -> dict[str, Any] | None:
        row = self.query_one(
            """
            SELECT * FROM personal_knowledge_base_files
            WHERE user_id = ? AND file_id = ? AND tombstoned_at IS NOT NULL
              AND cleanup_completed_at IS NULL
            """,
            (user_id, file_id),
        )
        return dict(row) if row is not None else None

    def list_generation_ids(self, user_id: str) -> list[str]:
        return [
            str(row["generation_id"])
            for row in self.query_all(
                """
                SELECT generation_id FROM personal_knowledge_base_generations
                WHERE user_id = ? AND status IN ('active', 'staging', 'retired')
                ORDER BY created_at, generation_id
                """,
                (user_id,),
            )
        ]

    def ensure_active_generation(
        self,
        *,
        user_id: str,
        collection_name: str,
        embedding_fingerprint: str,
        chunk_fingerprint: str,
        index_fingerprint: str,
        locator_schema_version: str,
    ) -> str:
        """Create the initial active generation or validate its fingerprints."""

        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._ensure_base(connection, user_id, now)
                self._ensure_not_purging(connection, user_id)
                base = connection.execute(
                    """
                    SELECT active_generation_id
                    FROM personal_knowledge_bases WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()
                generation_id = base["active_generation_id"]
                if generation_id is not None:
                    generation = connection.execute(
                        """
                        SELECT * FROM personal_knowledge_base_generations
                        WHERE user_id = ? AND generation_id = ? AND status = 'active'
                        """,
                        (user_id, generation_id),
                    ).fetchone()
                    if generation is None:
                        raise RuntimeError("active personal generation is inconsistent")
                    actual = (
                        generation["collection_name"],
                        generation["embedding_fingerprint"],
                        generation["chunk_fingerprint"],
                        generation["index_fingerprint"],
                        generation["locator_schema_version"],
                    )
                    expected = (
                        collection_name, embedding_fingerprint, chunk_fingerprint,
                        index_fingerprint, locator_schema_version,
                    )
                    if actual != expected:
                        raise RuntimeError(
                            "active personal generation requires a full rebuild"
                        )
                    connection.commit()
                    return str(generation_id)
                generation_id = f"personal_generation_{uuid.uuid4().hex}"
                connection.execute(
                    """
                    INSERT INTO personal_knowledge_base_generations (
                        generation_id, user_id, status, input_files_json,
                        collection_name, embedding_fingerprint,
                        chunk_fingerprint, index_fingerprint,
                        locator_schema_version, created_at, activated_at
                    ) VALUES (?, ?, 'active', '[]', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        generation_id, user_id, collection_name,
                        embedding_fingerprint, chunk_fingerprint,
                        index_fingerprint, locator_schema_version, now, now,
                    ),
                )
                connection.execute(
                    """
                    UPDATE personal_knowledge_bases
                    SET active_generation_id = ?, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (generation_id, now, user_id),
                )
                connection.commit()
                return generation_id
            except BaseException:
                connection.rollback()
                raise

    def begin_rebuild_generation(
        self,
        *,
        user_id: str,
        job_id: str,
        target_revision: int,
        file_ids: Iterable[str],
        collection_name: str,
        embedding_fingerprint: str,
        chunk_fingerprint: str,
        index_fingerprint: str,
        locator_schema_version: str,
    ) -> str:
        """Create or recover the staging generation owned by one rebuild job."""

        inputs = list(file_ids)
        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                job = connection.execute(
                    """
                    SELECT generation_id FROM personal_knowledge_base_jobs
                    WHERE user_id = ? AND job_id = ? AND job_type = 'rebuild'
                      AND target_revision = ? AND status = 'running'
                    """,
                    (user_id, job_id, target_revision),
                ).fetchone()
                if job is None:
                    raise RuntimeError("rebuild job is not staging eligible")
                if job["generation_id"] is not None:
                    generation = connection.execute(
                        """
                        SELECT * FROM personal_knowledge_base_generations
                        WHERE user_id = ? AND generation_id = ? AND status = 'staging'
                        """,
                        (user_id, job["generation_id"]),
                    ).fetchone()
                    if generation is None:
                        raise RuntimeError("rebuild staging generation is inconsistent")
                    connection.commit()
                    return str(job["generation_id"])
                generation_id = f"personal_generation_{uuid.uuid4().hex}"
                connection.execute(
                    """
                    INSERT INTO personal_knowledge_base_generations (
                        generation_id, user_id, status, input_files_json,
                        collection_name, embedding_fingerprint,
                        chunk_fingerprint, index_fingerprint,
                        locator_schema_version, created_at
                    ) VALUES (?, ?, 'staging', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        generation_id, user_id, json.dumps(inputs), collection_name,
                        embedding_fingerprint, chunk_fingerprint, index_fingerprint,
                        locator_schema_version, now,
                    ),
                )
                connection.execute(
                    """
                    UPDATE personal_knowledge_base_jobs
                    SET generation_id = ?, stage = 'preparing', updated_at = ?
                    WHERE user_id = ? AND job_id = ? AND status = 'running'
                    """,
                    (generation_id, now, user_id, job_id),
                )
                connection.execute(
                    """
                    UPDATE personal_knowledge_bases
                    SET building_generation_id = ?, status = 'building',
                        progress = MAX(progress, 0.05), updated_at = ?
                    WHERE user_id = ?
                    """,
                    (generation_id, now, user_id),
                )
                connection.commit()
                return generation_id
            except BaseException:
                connection.rollback()
                raise

    def update_job_progress(
        self,
        *,
        user_id: str,
        job_id: str,
        progress: float,
        stage: str | None = None,
        file_ids: Iterable[str] = (),
    ) -> bool:
        """Persist monotonic job, file and aggregate progress."""

        if not 0.0 <= progress <= 1.0:
            raise ValueError("progress must be between zero and one")
        now = self._now()
        owned_ids = list(dict.fromkeys(file_ids))
        with closing(self._connect()) as connection, connection:
            updated = connection.execute(
                """
                UPDATE personal_knowledge_base_jobs
                SET progress = MAX(progress, ?),
                    stage = COALESCE(?, stage), updated_at = ?
                WHERE user_id = ? AND job_id = ? AND status = 'running'
                RETURNING job_type
                """,
                (progress, stage, now, user_id, job_id),
            ).fetchone()
            if updated is None:
                return False
            if updated["job_type"] not in ("upload", "rebuild"):
                return True
            connection.execute(
                """
                UPDATE personal_knowledge_bases
                SET status = 'building', progress = MAX(progress, ?),
                    updated_at = ?
                WHERE user_id = ?
                """,
                (progress, now, user_id),
            )
            if owned_ids:
                placeholders = ",".join("?" for _ in owned_ids)
                connection.execute(
                    f"""
                    UPDATE personal_knowledge_base_files
                    SET status = 'building', progress = MAX(progress, ?),
                        updated_at = ?
                    WHERE user_id = ? AND tombstoned_at IS NULL
                      AND file_id IN ({placeholders})
                    """,
                    (progress, now, user_id, *owned_ids),
                )
            return True

    def mark_mutation_applying(
        self, *, user_id: str, target_revision: int, operation: str
    ) -> bool:
        """Durably record intent immediately before a Qdrant visible mutation."""

        now = self._now()
        return self.execute(
            """
            UPDATE personal_knowledge_base_mutations
            SET status = 'applying', attempts = attempts + 1, updated_at = ?
            WHERE user_id = ? AND target_revision = ? AND operation = ?
              AND status IN ('pending', 'applying', 'failed')
            """,
            (now, user_id, target_revision, operation),
        ) == 1

    def cancel_empty_upload_job(
        self, *, user_id: str, job_id: str, target_revision: int
    ) -> bool:
        """Settle an upload whose entire batch was tombstoned before publish."""

        now = self._now()
        with closing(self._connect()) as connection, connection:
            updated = connection.execute(
                """
                UPDATE personal_knowledge_base_jobs AS j
                SET status = 'cancelled', stage = 'cancelled',
                    completed_at = ?, updated_at = ?
                WHERE j.user_id = ? AND j.job_id = ? AND j.job_type = 'upload'
                  AND j.target_revision = ? AND j.status = 'running'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM json_each(j.payload_json, '$.file_ids') AS requested
                      JOIN personal_knowledge_base_files AS f
                        ON f.file_id = requested.value
                       AND f.user_id = j.user_id
                       AND f.tombstoned_at IS NULL
                  )
                """,
                (now, now, user_id, job_id, target_revision),
            ).rowcount
            if updated != 1:
                return False
            connection.execute(
                """
                UPDATE personal_knowledge_base_mutations
                SET status = 'failed', error = 'upload cancelled after tombstone',
                    updated_at = ?
                WHERE user_id = ? AND target_revision = ?
                  AND operation = 'publish_file' AND status != 'applied'
                """,
                (now, user_id, target_revision),
            )
            return True

    def cancel_rebuild_job(
        self,
        *,
        user_id: str,
        job_id: str,
        target_revision: int,
        generation_id: str | None,
        reason: str,
    ) -> bool:
        """Cancel a rebuild after its input tombstones changed under it."""

        now = self._now()
        with closing(self._connect()) as connection, connection:
            updated = connection.execute(
                """
                UPDATE personal_knowledge_base_jobs
                SET status = 'cancelled', stage = 'cancelled', error = ?,
                    completed_at = ?, updated_at = ?
                WHERE user_id = ? AND job_id = ? AND job_type = 'rebuild'
                  AND target_revision = ? AND status = 'running'
                """,
                (
                    self._error(reason), now, now, user_id, job_id,
                    target_revision,
                ),
            ).rowcount
            if updated != 1:
                return False
            connection.execute(
                """
                UPDATE personal_knowledge_base_mutations
                SET status = 'failed', error = ?, updated_at = ?
                WHERE user_id = ? AND target_revision = ?
                  AND operation = 'activate_generation' AND status != 'applied'
                """,
                (self._error(reason), now, user_id, target_revision),
            )
            if generation_id is not None:
                connection.execute(
                    """
                    UPDATE personal_knowledge_base_generations
                    SET status = 'failed'
                    WHERE user_id = ? AND generation_id = ? AND status = 'staging'
                    """,
                    (user_id, generation_id),
                )
            connection.execute(
                """
                UPDATE personal_knowledge_bases
                SET building_generation_id = NULL,
                    status = CASE
                        WHEN active_generation_id IS NULL THEN 'idle' ELSE 'ready'
                    END,
                    progress = CASE
                        WHEN active_generation_id IS NULL THEN 0.0 ELSE 1.0
                    END,
                    error = NULL, updated_at = ?
                WHERE user_id = ?
                """,
                (now, user_id),
            )
            return True

    def commit_upload_job(
        self,
        *,
        user_id: str,
        job_id: str,
        target_revision: int,
        generation_id: str,
        collection_name: str,
        files: Iterable[IndexedPersonalKnowledgeBaseFile],
    ) -> int:
        """Commit verified visible points and allocate one global mutation seq."""

        results = list(files)
        if not results:
            raise ValueError("upload commit requires at least one indexed file")
        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                job = connection.execute(
                    """
                    SELECT status, target_revision FROM personal_knowledge_base_jobs
                    WHERE user_id = ? AND job_id = ? AND job_type = 'upload'
                    """,
                    (user_id, job_id),
                ).fetchone()
                if (
                    job is None or job["status"] != "running"
                    or int(job["target_revision"]) != target_revision
                ):
                    raise RuntimeError("upload job is no longer commit eligible")
                for item in results:
                    updated = connection.execute(
                        """
                        UPDATE personal_knowledge_base_files
                        SET docir_manifest_path = ?, chunk_manifest_path = ?,
                            indexed_revision = ?, status = 'ready', progress = 1.0,
                            chunk_count = ?, index_count = ?, error = NULL,
                            updated_at = ?
                        WHERE user_id = ? AND file_id = ?
                          AND tombstoned_at IS NULL
                        """,
                        (
                            item.docir_manifest_path, item.chunk_manifest_path,
                            target_revision, item.chunk_count, item.index_count,
                            now, user_id, item.file_id,
                        ),
                    ).rowcount
                    if updated != 1:
                        raise RuntimeError("indexed file is no longer commit eligible")
                connection.execute(
                    """
                    INSERT INTO personal_knowledge_base_collection_state (
                        singleton_id, collection_name, updated_at
                    ) VALUES (1, ?, ?)
                    ON CONFLICT(singleton_id) DO UPDATE SET
                        collection_name = excluded.collection_name,
                        updated_at = excluded.updated_at
                    """,
                    (collection_name, now),
                )
                state = connection.execute(
                    """
                    UPDATE personal_knowledge_base_collection_state
                    SET qdrant_mutation_seq = qdrant_mutation_seq + 1,
                        snapshot_dirty = 1, updated_at = ?
                    WHERE singleton_id = 1
                    RETURNING qdrant_mutation_seq
                    """,
                    (now,),
                ).fetchone()
                mutation_seq = int(state[0])
                mutation = connection.execute(
                    """
                    UPDATE personal_knowledge_base_mutations
                    SET status = 'applied', qdrant_mutation_seq = ?,
                        applied_at = ?, updated_at = ?
                    WHERE user_id = ? AND target_revision = ?
                      AND operation = 'publish_file' AND status IN ('pending', 'applying')
                    """,
                    (mutation_seq, now, now, user_id, target_revision),
                ).rowcount
                if mutation != 1:
                    raise RuntimeError("upload mutation outbox is inconsistent")
                connection.execute(
                    """
                    UPDATE personal_knowledge_base_jobs
                    SET status = 'succeeded', stage = 'complete', progress = 1.0,
                        completed_at = ?, updated_at = ?
                    WHERE user_id = ? AND job_id = ? AND status = 'running'
                    """,
                    (now, now, user_id, job_id),
                )
                connection.execute(
                    """
                    UPDATE personal_knowledge_base_generations
                    SET chunk_count = (
                            SELECT COALESCE(SUM(chunk_count), 0)
                            FROM personal_knowledge_base_files
                            WHERE user_id = ? AND tombstoned_at IS NULL
                        ),
                        index_count = (
                            SELECT COALESCE(SUM(index_count), 0)
                            FROM personal_knowledge_base_files
                            WHERE user_id = ? AND tombstoned_at IS NULL
                        )
                    WHERE user_id = ? AND generation_id = ?
                    """,
                    (user_id, user_id, user_id, generation_id),
                )
                connection.execute(
                    """
                    UPDATE personal_knowledge_bases
                    SET indexed_revision = ?, status = 'ready', progress = 1.0,
                        chunk_count = (
                            SELECT COALESCE(SUM(chunk_count), 0)
                            FROM personal_knowledge_base_files
                            WHERE user_id = ? AND tombstoned_at IS NULL
                        ),
                        index_count = (
                            SELECT COALESCE(SUM(index_count), 0)
                            FROM personal_knowledge_base_files
                            WHERE user_id = ? AND tombstoned_at IS NULL
                        ),
                        error = NULL, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (target_revision, user_id, user_id, now, user_id),
                )
                connection.commit()
                return mutation_seq
            except BaseException:
                connection.rollback()
                raise

    def fail_job(
        self, *, user_id: str, job_id: str, error: str, retry: bool
    ) -> bool:
        """Persist a bounded retry or a display-safe terminal failure."""

        now = self._now()
        status = "queued" if retry else "failed"
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                UPDATE personal_knowledge_base_jobs
                SET status = ?, stage = CASE WHEN ? THEN 'queued' ELSE 'failed' END,
                    error = ?, started_at = NULL,
                    completed_at = CASE WHEN ? THEN NULL ELSE ? END,
                    updated_at = ?
                WHERE user_id = ? AND job_id = ? AND status = 'running'
                RETURNING payload_json, job_type, generation_id
                """,
                (
                    status, retry, self._error(error), retry, now, now, user_id, job_id,
                ),
            ).fetchone()
            if row is None:
                return False
            if not retry:
                payload = json.loads(row["payload_json"])
                file_ids = payload.get("file_ids", [])
                operation = {
                    "upload": "publish_file",
                    "delete": "delete_file",
                    "rebuild": "activate_generation",
                    "cleanup_generation": "delete_generation",
                }.get(row["job_type"])
                if operation is not None:
                    connection.execute(
                        """
                        UPDATE personal_knowledge_base_mutations
                        SET status = 'failed', error = ?, updated_at = ?
                        WHERE user_id = ? AND operation = ?
                          AND qdrant_mutation_seq IS NULL
                          AND status IN ('pending', 'applying')
                          AND target_revision = (
                              SELECT target_revision
                              FROM personal_knowledge_base_jobs
                              WHERE user_id = ? AND job_id = ?
                          )
                        """,
                        (
                            self._error(error), now, user_id, operation,
                            user_id, job_id,
                        ),
                    )
                if row["job_type"] == "upload" and file_ids:
                    placeholders = ",".join("?" for _ in file_ids)
                    connection.execute(
                        f"""
                        UPDATE personal_knowledge_base_files
                        SET status = 'failed', error = ?, updated_at = ?
                        WHERE user_id = ? AND tombstoned_at IS NULL
                          AND file_id IN ({placeholders})
                        """,
                        (self._error(error), now, user_id, *file_ids),
                    )
                if row["job_type"] == "rebuild":
                    if row["generation_id"] is not None:
                        connection.execute(
                            """
                            UPDATE personal_knowledge_base_generations
                            SET status = 'failed'
                            WHERE user_id = ? AND generation_id = ?
                              AND status = 'staging'
                            """,
                            (user_id, row["generation_id"]),
                        )
                    connection.execute(
                        """
                        UPDATE personal_knowledge_bases
                        SET building_generation_id = NULL,
                            status = CASE
                                WHEN active_generation_id IS NULL THEN 'failed'
                                ELSE 'ready'
                            END,
                            error = ?, updated_at = ?
                        WHERE user_id = ?
                        """,
                        (self._error(error), now, user_id),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE personal_knowledge_bases
                        SET status = 'failed', error = ?, updated_at = ?
                        WHERE user_id = ?
                        """,
                        (self._error(error), now, user_id),
                    )
            return True

    def commit_delete_index(
        self,
        *,
        user_id: str,
        job_id: str,
        target_revision: int,
        collection_name: str,
        file_id: str,
    ) -> int:
        """Record verified Qdrant deletion; clean-snapshot completion is separate."""

        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                eligible = connection.execute(
                    """
                    SELECT 1 FROM personal_knowledge_base_jobs
                    WHERE user_id = ? AND job_id = ? AND job_type = 'delete'
                      AND target_revision = ? AND status = 'running'
                    """,
                    (user_id, job_id, target_revision),
                ).fetchone()
                if eligible is None:
                    raise RuntimeError("delete job is no longer commit eligible")
                connection.execute(
                    """
                    INSERT INTO personal_knowledge_base_collection_state (
                        singleton_id, collection_name, updated_at
                    ) VALUES (1, ?, ?)
                    ON CONFLICT(singleton_id) DO UPDATE SET
                        collection_name = excluded.collection_name,
                        updated_at = excluded.updated_at
                    """,
                    (collection_name, now),
                )
                mutation_seq = int(
                    connection.execute(
                        """
                        UPDATE personal_knowledge_base_collection_state
                        SET qdrant_mutation_seq = qdrant_mutation_seq + 1,
                            snapshot_dirty = 1, updated_at = ?
                        WHERE singleton_id = 1
                        RETURNING qdrant_mutation_seq
                        """,
                        (now,),
                    ).fetchone()[0]
                )
                updated = connection.execute(
                    """
                    UPDATE personal_knowledge_base_mutations
                    SET status = 'applied', qdrant_mutation_seq = ?,
                        applied_at = ?, updated_at = ?
                    WHERE user_id = ? AND target_revision = ?
                      AND operation = 'delete_file'
                      AND status IN ('pending', 'applying')
                    """,
                    (mutation_seq, now, now, user_id, target_revision),
                ).rowcount
                if updated != 1:
                    raise RuntimeError("delete mutation outbox is inconsistent")
                connection.execute(
                    """
                    UPDATE personal_knowledge_base_files
                    SET chunk_count = 0, index_count = 0,
                        docir_manifest_path = NULL, chunk_manifest_path = NULL,
                        updated_at = ?
                    WHERE user_id = ? AND file_id = ?
                      AND tombstoned_at IS NOT NULL
                    """,
                    (now, user_id, file_id),
                )
                connection.execute(
                    """
                    UPDATE personal_knowledge_base_jobs
                    SET status = 'succeeded', stage = 'complete', progress = 1.0,
                        completed_at = ?, updated_at = ?
                    WHERE user_id = ? AND job_id = ? AND status = 'running'
                    """,
                    (now, now, user_id, job_id),
                )
                connection.execute(
                    """
                    UPDATE personal_knowledge_bases
                    SET indexed_revision = ?,
                        status = CASE WHEN file_count = 0 THEN 'idle' ELSE 'ready' END,
                        progress = CASE WHEN file_count = 0 THEN 0.0 ELSE 1.0 END,
                        chunk_count = (
                            SELECT COALESCE(SUM(chunk_count), 0)
                            FROM personal_knowledge_base_files
                            WHERE user_id = ? AND tombstoned_at IS NULL
                        ),
                        index_count = (
                            SELECT COALESCE(SUM(index_count), 0)
                            FROM personal_knowledge_base_files
                            WHERE user_id = ? AND tombstoned_at IS NULL
                        ),
                        error = NULL, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (target_revision, user_id, user_id, now, user_id),
                )
                connection.commit()
                return mutation_seq
            except BaseException:
                connection.rollback()
                raise

    def commit_rebuild_job(
        self,
        *,
        user_id: str,
        job_id: str,
        target_revision: int,
        generation_id: str,
        collection_name: str,
        files: Iterable[IndexedPersonalKnowledgeBaseFile],
    ) -> int:
        """Atomically activate verified staging and retain old generation for cleanup."""

        results = list(files)
        if not results:
            raise ValueError("rebuild commit requires indexed files")
        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                base = connection.execute(
                    """
                    SELECT active_generation_id, building_generation_id
                    FROM personal_knowledge_bases WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()
                job = connection.execute(
                    """
                    SELECT 1 FROM personal_knowledge_base_jobs
                    WHERE user_id = ? AND job_id = ? AND job_type = 'rebuild'
                      AND target_revision = ? AND generation_id = ?
                      AND status = 'running'
                    """,
                    (user_id, job_id, target_revision, generation_id),
                ).fetchone()
                if (
                    base is None or job is None
                    or base["building_generation_id"] != generation_id
                ):
                    raise RuntimeError("rebuild generation is no longer commit eligible")
                old_generation_id = base["active_generation_id"]
                for item in results:
                    if connection.execute(
                        """
                        UPDATE personal_knowledge_base_files
                        SET docir_manifest_path = ?, chunk_manifest_path = ?,
                            indexed_revision = ?, status = 'ready', progress = 1.0,
                            chunk_count = ?, index_count = ?, error = NULL,
                            updated_at = ?
                        WHERE user_id = ? AND file_id = ?
                          AND tombstoned_at IS NULL
                        """,
                        (
                            item.docir_manifest_path, item.chunk_manifest_path,
                            target_revision, item.chunk_count, item.index_count,
                            now, user_id, item.file_id,
                        ),
                    ).rowcount != 1:
                        raise RuntimeError("rebuild input changed before commit")
                connection.execute(
                    """
                    INSERT INTO personal_knowledge_base_collection_state (
                        singleton_id, collection_name, updated_at
                    ) VALUES (1, ?, ?)
                    ON CONFLICT(singleton_id) DO UPDATE SET
                        collection_name = excluded.collection_name,
                        updated_at = excluded.updated_at
                    """,
                    (collection_name, now),
                )
                mutation_seq = int(
                    connection.execute(
                        """
                        UPDATE personal_knowledge_base_collection_state
                        SET qdrant_mutation_seq = qdrant_mutation_seq + 1,
                            snapshot_dirty = 1, updated_at = ?
                        WHERE singleton_id = 1
                        RETURNING qdrant_mutation_seq
                        """,
                        (now,),
                    ).fetchone()[0]
                )
                if connection.execute(
                    """
                    UPDATE personal_knowledge_base_mutations
                    SET status = 'applied', qdrant_mutation_seq = ?,
                        applied_at = ?, updated_at = ?
                    WHERE user_id = ? AND target_revision = ?
                      AND operation = 'activate_generation'
                      AND status IN ('pending', 'applying')
                    """,
                    (mutation_seq, now, now, user_id, target_revision),
                ).rowcount != 1:
                    raise RuntimeError("rebuild mutation outbox is inconsistent")
                if old_generation_id is not None:
                    connection.execute(
                        """
                        UPDATE personal_knowledge_base_generations
                        SET status = 'retired', retired_at = ?
                        WHERE user_id = ? AND generation_id = ? AND status = 'active'
                        """,
                        (now, user_id, old_generation_id),
                    )
                totals = (
                    sum(item.chunk_count for item in results),
                    sum(item.index_count for item in results),
                )
                connection.execute(
                    """
                    UPDATE personal_knowledge_base_generations
                    SET status = 'active', chunk_count = ?, index_count = ?,
                        activated_at = ?
                    WHERE user_id = ? AND generation_id = ? AND status = 'staging'
                    """,
                    (totals[0], totals[1], now, user_id, generation_id),
                )
                connection.execute(
                    """
                    UPDATE personal_knowledge_bases
                    SET active_generation_id = ?, building_generation_id = NULL,
                        indexed_revision = ?, status = 'ready', progress = 1.0,
                        chunk_count = ?, index_count = ?, error = NULL,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        generation_id, target_revision, totals[0], totals[1],
                        now, user_id,
                    ),
                )
                connection.execute(
                    """
                    UPDATE personal_knowledge_base_jobs
                    SET status = 'succeeded', stage = 'complete', progress = 1.0,
                        completed_at = ?, updated_at = ?
                    WHERE user_id = ? AND job_id = ? AND status = 'running'
                    """,
                    (now, now, user_id, job_id),
                )
                if old_generation_id is not None:
                    cleanup_job_id = str(uuid.uuid4())
                    payload = json.dumps({"generation_id": old_generation_id})
                    connection.execute(
                        """
                        INSERT INTO personal_knowledge_base_jobs (
                            job_id, user_id, job_type, target_revision,
                            generation_id, payload_json, created_at, updated_at
                        ) VALUES (?, ?, 'cleanup_generation', ?, ?, ?, ?, ?)
                        """,
                        (
                            cleanup_job_id, user_id, target_revision,
                            old_generation_id, payload, now, now,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO personal_knowledge_base_mutations (
                            mutation_id, user_id, target_revision, operation,
                            payload_json, status, created_at, updated_at
                        ) VALUES (?, ?, ?, 'delete_generation', ?, 'pending', ?, ?)
                        """,
                        (
                            str(uuid.uuid4()), user_id, target_revision,
                            payload, now, now,
                        ),
                    )
                connection.commit()
                return mutation_seq
            except BaseException:
                connection.rollback()
                raise

    def commit_generation_cleanup(
        self,
        *,
        user_id: str,
        job_id: str,
        target_revision: int,
        generation_id: str,
        collection_name: str,
    ) -> int:
        """Commit verified removal of a retired generation."""

        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                eligible = connection.execute(
                    """
                    SELECT 1 FROM personal_knowledge_base_jobs
                    WHERE user_id = ? AND job_id = ?
                      AND job_type = 'cleanup_generation'
                      AND target_revision = ? AND generation_id = ?
                      AND status = 'running'
                    """,
                    (user_id, job_id, target_revision, generation_id),
                ).fetchone()
                if eligible is None:
                    raise RuntimeError("generation cleanup is no longer eligible")
                mutation_seq = int(
                    connection.execute(
                        """
                        UPDATE personal_knowledge_base_collection_state
                        SET qdrant_mutation_seq = qdrant_mutation_seq + 1,
                            snapshot_dirty = 1, updated_at = ?
                        WHERE singleton_id = 1 AND collection_name = ?
                        RETURNING qdrant_mutation_seq
                        """,
                        (now, collection_name),
                    ).fetchone()[0]
                )
                if connection.execute(
                    """
                    UPDATE personal_knowledge_base_mutations
                    SET status = 'applied', qdrant_mutation_seq = ?,
                        applied_at = ?, updated_at = ?
                    WHERE user_id = ? AND target_revision = ?
                      AND operation = 'delete_generation'
                      AND status IN ('pending', 'applying')
                    """,
                    (mutation_seq, now, now, user_id, target_revision),
                ).rowcount != 1:
                    raise RuntimeError("generation cleanup outbox is inconsistent")
                connection.execute(
                    """
                    UPDATE personal_knowledge_base_generations
                    SET status = 'retired', retired_at = COALESCE(retired_at, ?),
                        chunk_count = 0, index_count = 0
                    WHERE user_id = ? AND generation_id = ?
                    """,
                    (now, user_id, generation_id),
                )
                connection.execute(
                    """
                    UPDATE personal_knowledge_base_jobs
                    SET status = 'succeeded', stage = 'complete', progress = 1.0,
                        completed_at = ?, updated_at = ?
                    WHERE user_id = ? AND job_id = ? AND status = 'running'
                    """,
                    (now, now, user_id, job_id),
                )
                connection.commit()
                return mutation_seq
            except BaseException:
                connection.rollback()
                raise

    def claim_next_job(
        self, *, job_types: Iterable[str] | None = None
    ) -> dict[str, Any] | None:
        """Atomically claim an eligible user's lowest unfinished revision."""

        now = self._now()
        accepted_types = tuple(dict.fromkeys(job_types or ()))
        type_clause = ""
        type_params: tuple[str, ...] = ()
        if accepted_types:
            type_clause = (
                "AND candidate.job_type IN ("
                + ",".join("?" for _ in accepted_types)
                + ")"
            )
            type_params = accepted_types
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    f"""
                    SELECT candidate.*
                    FROM personal_knowledge_base_jobs AS candidate
                    WHERE candidate.status = 'queued'
                      {type_clause}
                      AND NOT EXISTS (
                          SELECT 1 FROM personal_knowledge_base_jobs AS earlier
                          WHERE earlier.user_id = candidate.user_id
                            AND earlier.target_revision < candidate.target_revision
                            AND earlier.status NOT IN ('succeeded', 'cancelled')
                      )
                    ORDER BY candidate.created_at, candidate.job_id
                    LIMIT 1
                    """,
                    type_params,
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                updated = connection.execute(
                    """
                    UPDATE personal_knowledge_base_jobs
                    SET status = 'running', stage = 'preparing', attempts = attempts + 1,
                        started_at = COALESCE(started_at, ?), updated_at = ?
                    WHERE job_id = ? AND user_id = ? AND status = 'queued'
                    """,
                    (now, now, row["job_id"], row["user_id"]),
                ).rowcount
                if updated != 1:
                    connection.rollback()
                    return None
                connection.commit()
                value = dict(row)
                value["status"] = "running"
                value["stage"] = "preparing"
                value["attempts"] += 1
                value["payload"] = json.loads(value.pop("payload_json"))
                return value
            except BaseException:
                connection.rollback()
                raise

    def finish_job(
        self,
        *,
        user_id: str,
        job_id: str,
        succeeded: bool,
        error: str | None = None,
    ) -> bool:
        """Finish an owned running job without permitting cross-user updates."""

        now = self._now()
        return self.execute(
            """
            UPDATE personal_knowledge_base_jobs
            SET status = ?, stage = CASE WHEN ? THEN 'complete' ELSE 'failed' END,
                progress = CASE WHEN ? THEN 1.0 ELSE progress END,
                error = ?, completed_at = ?, updated_at = ?
            WHERE user_id = ? AND job_id = ? AND status = 'running'
            """,
            (
                "succeeded" if succeeded else "failed",
                succeeded,
                succeeded,
                self._error(error),
                now,
                now,
                user_id,
                job_id,
            ),
        ) == 1

    def retry_failed_job(self, *, user_id: str, job_id: str) -> bool:
        """Explicitly requeue one owned terminal failure without skipping order."""

        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """
                    SELECT job_type, target_revision, generation_id, payload_json
                    FROM personal_knowledge_base_jobs
                    WHERE user_id = ? AND job_id = ? AND status = 'failed'
                    """,
                    (user_id, job_id),
                ).fetchone()
                if row is None:
                    connection.commit()
                    return False
                operation = {
                    "upload": "publish_file",
                    "delete": "delete_file",
                    "rebuild": "activate_generation",
                    "cleanup_generation": "delete_generation",
                }.get(row["job_type"])
                if operation is None:
                    raise RuntimeError("unsupported failed personal job type")
                mutation = connection.execute(
                    """
                    UPDATE personal_knowledge_base_mutations
                    SET status = 'pending', error = NULL, updated_at = ?
                    WHERE user_id = ? AND target_revision = ? AND operation = ?
                      AND status = 'failed' AND qdrant_mutation_seq IS NULL
                    """,
                    (now, user_id, row["target_revision"], operation),
                ).rowcount
                if mutation != 1:
                    raise RuntimeError("failed job mutation is not retry eligible")
                connection.execute(
                    """
                    UPDATE personal_knowledge_base_jobs
                    SET status = 'queued', stage = 'queued', progress = 0.0,
                        error = NULL, started_at = NULL, completed_at = NULL,
                        updated_at = ?
                    WHERE user_id = ? AND job_id = ? AND status = 'failed'
                    """,
                    (now, user_id, job_id),
                )
                payload = json.loads(row["payload_json"])
                if row["job_type"] == "upload":
                    file_ids = payload.get("file_ids", [])
                    if file_ids:
                        placeholders = ",".join("?" for _ in file_ids)
                        connection.execute(
                            f"""
                            UPDATE personal_knowledge_base_files
                            SET status = 'queued', progress = 0.0,
                                error = NULL, updated_at = ?
                            WHERE user_id = ? AND tombstoned_at IS NULL
                              AND file_id IN ({placeholders})
                            """,
                            (now, user_id, *file_ids),
                        )
                if row["job_type"] == "rebuild" and row["generation_id"] is not None:
                    connection.execute(
                        """
                        UPDATE personal_knowledge_base_generations
                        SET status = 'staging'
                        WHERE user_id = ? AND generation_id = ? AND status = 'failed'
                        """,
                        (user_id, row["generation_id"]),
                    )
                    connection.execute(
                        """
                        UPDATE personal_knowledge_bases
                        SET building_generation_id = ?, status = 'queued',
                            progress = 0.0, error = NULL, updated_at = ?
                        WHERE user_id = ?
                        """,
                        (row["generation_id"], now, user_id),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE personal_knowledge_bases
                        SET status = 'queued', progress = 0.0,
                            error = NULL, updated_at = ?
                        WHERE user_id = ?
                        """,
                        (now, user_id),
                    )
                connection.commit()
                return True
            except BaseException:
                connection.rollback()
                raise

    def retry_failed_generation_cleanup(
        self, *, user_id: str, generation_id: str
    ) -> str | None:
        """Requeue the failed cleanup job for one owned retired generation."""

        row = self.query_one(
            """
            SELECT job_id FROM personal_knowledge_base_jobs
            WHERE user_id = ? AND generation_id = ?
              AND job_type = 'cleanup_generation' AND status = 'failed'
            ORDER BY created_at DESC, job_id DESC LIMIT 1
            """,
            (user_id, generation_id),
        )
        if row is None:
            return None
        job_id = str(row["job_id"])
        return job_id if self.retry_failed_job(user_id=user_id, job_id=job_id) else None
