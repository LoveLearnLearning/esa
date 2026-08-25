"""Persistence tests for personal knowledge bases."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from backend.core.stores import migrations
from backend.core.stores.migrations import run_migrations
from backend.core.stores.personal_knowledge_base_store import (
    NewPersonalKnowledgeBaseFile,
    PersonalKnowledgeBaseConflict,
    PersonalKnowledgeBaseNotFound,
    PersonalKnowledgeBaseQuotaExceeded,
    PersonalKnowledgeBaseStore,
)
from backend.core.stores.user_store import UserStore


def _database(tmp_path):
    database = tmp_path / "user.db"
    UserStore(database)
    run_migrations(database)
    return database


def test_personal_knowledge_base_migration_creates_tenant_schema(tmp_path):
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "personal_knowledge_bases",
            "personal_knowledge_base_files",
            "personal_knowledge_base_jobs",
            "personal_knowledge_base_generations",
            "personal_knowledge_base_collection_state",
            "personal_knowledge_base_mutations",
            "personal_knowledge_base_snapshots",
            "personal_knowledge_base_upload_reservations",
            "personal_knowledge_base_job_stage_events",
            "personal_knowledge_base_user_purges",
            "personal_knowledge_base_catalogs",
        } <= tables
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_catalog_migration_backfills_existing_files(tmp_path, monkeypatch):
    database = tmp_path / "legacy.db"
    UserStore(database)
    all_migrations = migrations.MIGRATIONS
    monkeypatch.setattr(
        migrations,
        "MIGRATIONS",
        [item for item in all_migrations if item[0] < 20],
    )
    run_migrations(database)
    connection = sqlite3.connect(database)
    now = "2026-08-21T00:00:00+00:00"
    connection.execute(
        "INSERT INTO users (id, username, password_hash) VALUES ('u1', 'one', 'hash')"
    )
    connection.execute(
        """
        INSERT INTO personal_knowledge_bases (user_id, created_at, updated_at)
        VALUES ('u1', ?, ?)
        """,
        (now, now),
    )
    connection.execute(
        """
        INSERT INTO personal_knowledge_base_files (
            file_id, user_id, filename, suffix, media_type, size_bytes,
            sha256, source_path, ingestion_revision, uploaded_at, updated_at
        ) VALUES ('file-1', 'u1', 'notes.txt', '.txt', 'text/plain', 1,
                  ?, '/durable/file-1/source.txt', 1, ?, ?)
        """,
        ("a" * 64, now, now),
    )
    connection.commit()
    connection.close()

    monkeypatch.setattr(migrations, "MIGRATIONS", all_migrations)
    assert run_migrations(database) == 2

    connection = sqlite3.connect(database)
    try:
        catalog_id = connection.execute(
            "SELECT knowledge_base_id FROM personal_knowledge_base_catalogs WHERE user_id = 'u1'"
        ).fetchone()[0]
        assert connection.execute(
            "SELECT knowledge_base_id FROM personal_knowledge_base_files WHERE file_id = 'file-1'"
        ).fetchone() == (catalog_id,)
    finally:
        connection.close()


def test_catalogs_keep_independent_active_generations(tmp_path):
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO users (id, username, password_hash) VALUES ('u1', 'one', 'hash')"
    )
    connection.commit()
    connection.close()

    store = PersonalKnowledgeBaseStore(database)
    first = store.resolve_knowledge_base_id(user_id="u1")
    second = store.create_knowledge_base(user_id="u1", name="第二库")["id"]
    kwargs = {
        "collection_name": "personal",
        "embedding_fingerprint": "e",
        "chunk_fingerprint": "c",
        "index_fingerprint": "i",
        "locator_schema_version": "l",
    }
    first_generation = store.ensure_active_generation(
        user_id="u1", knowledge_base_id=first, **kwargs
    )
    second_generation = store.ensure_active_generation(
        user_id="u1", knowledge_base_id=second, **kwargs
    )

    assert first_generation != second_generation
    assert store.get_retrieval_state("u1", first)["generation_id"] == first_generation
    assert store.get_retrieval_state("u1", second)["generation_id"] == second_generation


def test_user_purge_is_replayable_and_survives_main_user_deletion(tmp_path):
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    now = "2026-08-21T00:00:00+00:00"
    connection.executemany(
        "INSERT INTO users (id, username, password_hash) VALUES (?, ?, 'hash')",
        (("u1", "one"), ("u2", "two")),
    )
    for user_id in ("u1", "u2"):
        generation_id = f"generation-{user_id}"
        file_id = f"file-{user_id}"
        connection.execute(
            """
            INSERT INTO personal_knowledge_base_generations (
                generation_id, user_id, status, collection_name,
                embedding_fingerprint, chunk_fingerprint, index_fingerprint,
                locator_schema_version, created_at, activated_at
            ) VALUES (?, ?, 'active', 'personal', 'embedding', 'chunk',
                      'index', 'locator', ?, ?)
            """,
            (generation_id, user_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO personal_knowledge_bases (
                user_id, status, active_generation_id, created_at, updated_at
            ) VALUES (?, 'ready', ?, ?, ?)
            """,
            (user_id, generation_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO personal_knowledge_base_files (
                file_id, user_id, filename, suffix, media_type, size_bytes,
                sha256, source_path, ingestion_revision, status,
                uploaded_at, updated_at
            ) VALUES (?, ?, ?, '.txt', 'text/plain', 1, ?, ?, 1,
                      'ready', ?, ?)
            """,
            (file_id, user_id, f"{user_id}.txt", user_id[1] * 64,
             f"/durable/{file_id}/source.txt", now, now),
        )
    connection.commit()
    connection.close()

    store = PersonalKnowledgeBaseStore(database)
    store.ensure_collection_state("personal")
    purge = store.begin_user_purge("u1")
    assert purge["file_ids"] == ["file-u1"]
    with pytest.raises(PersonalKnowledgeBaseConflict):
        store.reserve_upload_capacity(
            user_id="u1", reserved_files=1, reserved_bytes=1,
            max_user_files=10, max_user_bytes=10,
        )

    assert store.mark_user_purge_applying(
        purge_id=purge["purge_id"], user_id="u1"
    ) is True
    sequence = store.commit_user_purge(
        purge_id=purge["purge_id"], user_id="u1"
    )
    assert sequence == 1
    assert [item["operation"] for item in store.list_applied_mutations_after(0)] == [
        "delete_user"
    ]
    authority = store.list_collection_rebuild_authority()
    assert [item["user_id"] for item in authority] == ["u2"]

    connection = sqlite3.connect(database)
    try:
        for table in (
            "personal_knowledge_bases",
            "personal_knowledge_base_files",
            "personal_knowledge_base_generations",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE user_id = 'u1'"
            ).fetchone()[0] == 0
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE user_id = 'u2'"
            ).fetchone()[0] == 1
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DELETE FROM users WHERE id = 'u1'")
        connection.commit()
        assert connection.execute(
            """
            SELECT status FROM personal_knowledge_base_user_purges
            WHERE user_id = 'u1'
            """
        ).fetchone() == ("applied",)
    finally:
        connection.close()

def test_upload_quota_reservations_prevent_concurrent_oversell(tmp_path):
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO users (id, username, password_hash) VALUES ('u1', 'one', 'hash')"
    )
    connection.commit()
    connection.close()
    store = PersonalKnowledgeBaseStore(database)

    first = store.reserve_upload_capacity(
        user_id="u1",
        reserved_files=1,
        reserved_bytes=80,
        max_user_files=2,
        max_user_bytes=100,
    )
    with pytest.raises(PersonalKnowledgeBaseQuotaExceeded):
        store.reserve_upload_capacity(
            user_id="u1",
            reserved_files=1,
            reserved_bytes=30,
            max_user_files=2,
            max_user_bytes=100,
        )

    assert store.release_upload_reservation(
        user_id="u1", reservation_id=first
    ) is True
    second = store.reserve_upload_capacity(
        user_id="u1",
        reserved_files=1,
        reserved_bytes=30,
        max_user_files=2,
        max_user_bytes=100,
    )
    assert store.clear_upload_reservations() == 1
    assert store.release_upload_reservation(
        user_id="u1", reservation_id=second
    ) is False


def test_live_file_sha_is_unique_only_within_logical_knowledge_base(tmp_path):
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    connection.executemany(
        """
        INSERT INTO users (id, username, password_hash)
        VALUES (?, ?, 'hash')
        """,
        (("u1", "user-one"), ("u2", "user-two")),
    )
    connection.commit()
    connection.close()
    store = PersonalKnowledgeBaseStore(database)
    first_kb = store.resolve_knowledge_base_id(user_id="u1")
    second_kb = store.create_knowledge_base(user_id="u1", name="第二知识库")["id"]
    other_user_kb = store.resolve_knowledge_base_id(user_id="u2")

    connection = sqlite3.connect(database)
    try:
        now = "2026-08-21T00:00:00+00:00"
        row = (
            "u1-file", "u1", first_kb, "first.txt", ".txt", "text/plain", 1,
            "a" * 64, "/durable/u1-file/source.txt", 1, now, now,
        )
        connection.execute(
            """
            INSERT INTO personal_knowledge_base_files (
                file_id, user_id, knowledge_base_id, filename, suffix, media_type, size_bytes,
                sha256, source_path, ingestion_revision, uploaded_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO personal_knowledge_base_files (
                    file_id, user_id, knowledge_base_id, filename, suffix, media_type, size_bytes,
                    sha256, source_path, ingestion_revision, uploaded_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("u1-copy", *row[1:]),
            )
        connection.execute(
            """
            INSERT INTO personal_knowledge_base_files (
                file_id, user_id, knowledge_base_id, filename, suffix, media_type, size_bytes,
                sha256, source_path, ingestion_revision, uploaded_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("u1-other-kb", "u1", second_kb, *row[3:]),
        )
        connection.execute(
            """
            INSERT INTO personal_knowledge_base_files (
                file_id, user_id, knowledge_base_id, filename, suffix, media_type, size_bytes,
                sha256, source_path, ingestion_revision, uploaded_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("u2-file", "u2", other_user_kb, *row[3:]),
        )
    finally:
        connection.close()


def test_catalog_listing_and_ownership_are_tenant_scoped(tmp_path):
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    connection.executemany(
        "INSERT INTO users (id, username, password_hash) VALUES (?, ?, 'hash')",
        (("u1", "user-one"), ("u2", "user-two")),
    )
    connection.commit()
    connection.close()
    store = PersonalKnowledgeBaseStore(database)

    default_id = store.resolve_knowledge_base_id(user_id="u1")
    created = store.create_knowledge_base(user_id="u1", name="课程 A")

    assert [(item["id"], item["name"]) for item in store.list_knowledge_bases("u1")] == [
        (default_id, "默认知识库"),
        (created["id"], "课程 A"),
    ]
    with pytest.raises(PersonalKnowledgeBaseConflict):
        store.create_knowledge_base(user_id="u1", name="课程 a")
    with pytest.raises(PersonalKnowledgeBaseNotFound):
        store.resolve_knowledge_base_id(
            user_id="u2",
            knowledge_base_id=created["id"],
        )


def test_retrieval_state_exposes_only_selected_library_file_ids(tmp_path):
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO users (id, username, password_hash) VALUES ('u1', 'one', 'hash')"
    )
    connection.commit()
    connection.close()
    store = PersonalKnowledgeBaseStore(database)
    kb_a = store.resolve_knowledge_base_id(user_id="u1")
    kb_b = store.create_knowledge_base(user_id="u1", name="知识库 B")["id"]
    store.ensure_collection_state("personal")
    store.ensure_active_generation(
        user_id="u1",
        collection_name="personal",
        embedding_fingerprint="embedding",
        chunk_fingerprint="chunk",
        index_fingerprint="index",
        locator_schema_version="locator",
    )
    store.mark_collection_ready(ready=True)
    now = "2026-08-21T00:00:00+00:00"
    connection = sqlite3.connect(database)
    connection.executemany(
        """
        INSERT INTO personal_knowledge_base_files (
            file_id, user_id, knowledge_base_id, filename, suffix, media_type,
            size_bytes, sha256, source_path, ingestion_revision, status,
            uploaded_at, updated_at
        ) VALUES (?, 'u1', ?, ?, '.txt', 'text/plain', 1, ?, ?, 1,
                  'ready', ?, ?)
        """,
        (
            ("file-a", kb_a, "a.txt", "a" * 64, "/durable/a", now, now),
            ("file-b", kb_b, "b.txt", "b" * 64, "/durable/b", now, now),
        ),
    )
    connection.commit()
    connection.close()

    assert store.get_retrieval_state("u1", kb_a)["files"] == {
        "file-a": "a.txt"
    }
    assert store.get_retrieval_state("u1", kb_b)["files"] == {
        "file-b": "b.txt"
    }


def test_snapshot_commit_preserves_dirty_when_sequence_advanced(tmp_path):
    database = _database(tmp_path)
    store = PersonalKnowledgeBaseStore(database)
    store.ensure_collection_state("personal")
    store.execute(
        """
        UPDATE personal_knowledge_base_collection_state
        SET qdrant_mutation_seq = 7, snapshot_dirty = 1
        WHERE singleton_id = 1
        """
    )
    snapshot_path = tmp_path / "snapshot.snapshot"
    store.begin_snapshot(
        snapshot_id="snapshot-1",
        snapshot_path=str(snapshot_path),
        collection_name="personal",
        point_count=12,
        qdrant_mutation_seq=7,
        embedding_fingerprint="embedding",
        index_fingerprint="index",
        locator_schema_version="personal-locator-0.1",
    )
    store.execute(
        """
        UPDATE personal_knowledge_base_collection_state
        SET qdrant_mutation_seq = 8
        WHERE singleton_id = 1
        """
    )

    store.commit_snapshot(snapshot_id="snapshot-1", sha256="a" * 64)

    state = store.get_collection_state()
    assert state is not None
    assert state["snapshot_mutation_seq"] == 7
    assert state["qdrant_mutation_seq"] == 8
    assert state["snapshot_dirty"] == 1
    assert store.list_valid_snapshots()[0]["sha256"] == "a" * 64


def test_terminal_failure_requires_explicit_outbox_retry(tmp_path):
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO users (id, username, password_hash) VALUES ('u1', 'u1', 'hash')"
    )
    connection.commit()
    connection.close()
    store = PersonalKnowledgeBaseStore(database)
    _ids, job_id = store.create_upload(
        user_id="u1",
        files=(
            NewPersonalKnowledgeBaseFile(
                file_id="12345678-1234-5678-1234-567812345678",
                filename="notes.txt",
                suffix=".txt",
                media_type="text/plain",
                size_bytes=1,
                sha256="a" * 64,
                source_path=str(tmp_path / "source.txt"),
                uploaded_at=datetime.now(timezone.utc).isoformat(),
            ),
        ),
    )
    assert job_id is not None
    claimed = store.claim_next_job(job_types=("upload",))
    assert claimed is not None
    assert store.fail_job(
        user_id="u1", job_id=job_id, error="safe failure", retry=False
    )
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT status, stage FROM personal_knowledge_base_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone() == ("failed", "failed")
        assert connection.execute(
            "SELECT status FROM personal_knowledge_base_mutations"
        ).fetchone() == ("failed",)
    finally:
        connection.close()

    assert store.retry_failed_job(user_id="u1", job_id=job_id)
    retried = store.claim_next_job(job_types=("upload",))
    assert retried is not None and retried["job_id"] == job_id
    assert retried["stage"] == "preparing"


def test_revision_claim_order_restart_recovery_and_tombstone_race(tmp_path):
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO users (id, username, password_hash) VALUES ('u1', 'u1', 'hash')"
    )
    connection.commit()
    connection.close()
    store = PersonalKnowledgeBaseStore(database)
    file_id = "12345678-1234-5678-1234-567812345678"
    _ids, upload_job_id = store.create_upload(
        user_id="u1",
        files=(
            NewPersonalKnowledgeBaseFile(
                file_id=file_id,
                filename="notes.txt",
                suffix=".txt",
                media_type="text/plain",
                size_bytes=1,
                sha256="b" * 64,
                source_path=str(tmp_path / "source.txt"),
                uploaded_at=datetime.now(timezone.utc).isoformat(),
            ),
        ),
    )
    assert upload_job_id is not None
    assert store.tombstone_file(user_id="u1", file_id=file_id)
    assert store.get_snapshot("u1")["files"] == []
    tombstone = store.get_tombstoned_file(user_id="u1", file_id=file_id)
    assert tombstone is not None and tombstone["cleanup_completed_at"] is None
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM personal_knowledge_base_jobs WHERE job_type = 'delete'"
        ).fetchone() == (1,)
    finally:
        connection.close()

    upload = store.claim_next_job(job_types=("upload", "delete"))
    assert upload is not None
    assert upload["job_id"] == upload_job_id
    assert upload["target_revision"] == 1
    assert store.claim_next_job(job_types=("upload", "delete")) is None

    assert store.recover_running_jobs() == 1
    replay = store.claim_next_job(job_types=("upload", "delete"))
    assert replay is not None and replay["job_id"] == upload_job_id
    assert store.cancel_empty_upload_job(
        user_id="u1", job_id=upload_job_id, target_revision=1
    )
    deletion = store.claim_next_job(job_types=("upload", "delete"))
    assert deletion is not None
    assert deletion["job_type"] == "delete"
    assert deletion["target_revision"] == 2


def test_progress_is_monotonic_and_stage_metrics_are_persisted(tmp_path):
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO users (id, username, password_hash) VALUES ('u1', 'u1', 'hash')"
    )
    connection.commit()
    connection.close()
    store = PersonalKnowledgeBaseStore(database)
    file_id = "22345678-1234-5678-1234-567812345678"
    _ids, job_id = store.create_upload(
        user_id="u1",
        files=(
            NewPersonalKnowledgeBaseFile(
                file_id=file_id,
                filename="notes.txt",
                suffix=".txt",
                media_type="text/plain",
                size_bytes=1,
                sha256="c" * 64,
                source_path=str(tmp_path / "source.txt"),
                uploaded_at=datetime.now(timezone.utc).isoformat(),
            ),
        ),
    )
    assert job_id is not None
    assert store.claim_next_job(job_types=("upload",)) is not None
    assert store.update_job_progress(
        user_id="u1", job_id=job_id, progress=0.8,
        stage="embedding", file_ids=(file_id,),
    )
    assert store.update_job_progress(
        user_id="u1", job_id=job_id, progress=0.2,
        stage="indexing", file_ids=(file_id,),
    )

    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT progress, stage FROM personal_knowledge_base_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone() == (0.8, "indexing")
    finally:
        connection.close()
    metrics = store.get_operational_metrics()
    assert metrics["jobs_by_stage"] == {"indexing": 1}
    assert metrics["stage_duration_seconds"]["embedding"]["samples"] == 1


def test_audit_cleanup_keeps_failed_retry_and_mutation_journal(tmp_path):
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO users (id, username, password_hash) VALUES ('u1', 'u1', 'hash')"
    )
    connection.execute(
        """
        INSERT INTO personal_knowledge_bases (
            user_id, status, progress, created_at, updated_at
        ) VALUES ('u1', 'idle', 0, '2025-01-01', '2025-01-01')
        """
    )
    for revision, (job_id, status) in enumerate(
        (("done", "succeeded"), ("retry", "failed")), start=1
    ):
        connection.execute(
            """
            INSERT INTO personal_knowledge_base_jobs (
                job_id, user_id, job_type, status, stage, target_revision,
                payload_json, created_at, updated_at, completed_at
            ) VALUES (?, 'u1', 'delete', ?, ?, ?, '{}',
                      '2025-01-01', '2025-01-01', '2025-01-01')
            """,
            (
                job_id, status,
                "complete" if status == "succeeded" else "failed",
                revision,
            ),
        )
    connection.execute(
        """
        INSERT INTO personal_knowledge_base_mutations (
            mutation_id, user_id, target_revision, operation, payload_json,
            status, qdrant_mutation_seq, created_at, applied_at, updated_at
        ) VALUES ('journal', 'u1', 1, 'delete_file', '{}', 'applied', 1,
                  '2025-01-01', '2025-01-01', '2025-01-01')
        """
    )
    connection.commit()
    connection.close()

    removed = PersonalKnowledgeBaseStore(database).cleanup_audit_records(
        completed_before="2026-01-01T00:00:00+00:00"
    )

    assert removed["jobs"] == 1
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT job_id FROM personal_knowledge_base_jobs"
        ).fetchall() == [("retry",)]
        assert connection.execute(
            "SELECT mutation_id FROM personal_knowledge_base_mutations"
        ).fetchall() == [("journal",)]
    finally:
        connection.close()


def test_batch_files_are_recorded_once_and_snapshot_order_is_stable(tmp_path):
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO users (id, username, password_hash) VALUES ('u1', 'u1', 'hash')"
    )
    connection.commit()
    connection.close()
    store = PersonalKnowledgeBaseStore(database)
    first = NewPersonalKnowledgeBaseFile(
        file_id="32345678-1234-5678-1234-567812345678",
        filename="first.txt", suffix=".txt", media_type="text/plain",
        size_bytes=1, sha256="d" * 64, source_path=str(tmp_path / "first"),
        uploaded_at="2026-01-01T00:00:00+00:00",
    )
    second = NewPersonalKnowledgeBaseFile(
        file_id="42345678-1234-5678-1234-567812345678",
        filename="second.txt", suffix=".txt", media_type="text/plain",
        size_bytes=1, sha256="e" * 64, source_path=str(tmp_path / "second"),
        uploaded_at="2026-01-02T00:00:00+00:00",
    )

    ids, job_id = store.create_upload(user_id="u1", files=(first, second))

    assert ids == [first.file_id, second.file_id]
    assert job_id is not None
    snapshot = store.get_snapshot("u1")
    assert [item["id"] for item in snapshot["files"]] == [
        second.file_id, first.file_id
    ]
    assert store.get_snapshot("u1")["files"] == snapshot["files"]


def test_job_state_constraints_and_claim_transition_are_enforced(tmp_path):
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO users (id, username, password_hash) VALUES ('u1', 'u1', 'hash')"
    )
    connection.commit()
    connection.close()
    store = PersonalKnowledgeBaseStore(database)
    _ids, job_id = store.create_upload(
        user_id="u1",
        files=(
            NewPersonalKnowledgeBaseFile(
                file_id="52345678-1234-5678-1234-567812345678",
                filename="notes.txt", suffix=".txt", media_type="text/plain",
                size_bytes=1, sha256="f" * 64,
                source_path=str(tmp_path / "source"),
                uploaded_at="2026-01-01T00:00:00+00:00",
            ),
        ),
    )
    claimed = store.claim_next_job(job_types=("upload",))
    assert claimed is not None and claimed["job_id"] == job_id
    assert store.claim_next_job(job_types=("upload",)) is None
    assert not store.cancel_empty_upload_job(
        user_id="u1", job_id=str(job_id), target_revision=1
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.execute(
            "UPDATE personal_knowledge_base_jobs SET status = 'impossible' WHERE job_id = ?",
            (job_id,),
        )


def test_cancelled_rebuild_fails_staging_and_preserves_active_generation(tmp_path):
    database = _database(tmp_path)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO users (id, username, password_hash) VALUES ('u1', 'u1', 'hash')"
    )
    connection.commit()
    connection.close()
    store = PersonalKnowledgeBaseStore(database)
    file_id = "62345678-1234-5678-1234-567812345678"
    _ids, upload_job_id = store.create_upload(
        user_id="u1",
        files=(
            NewPersonalKnowledgeBaseFile(
                file_id=file_id, filename="notes.txt", suffix=".txt",
                media_type="text/plain", size_bytes=1, sha256="1" * 64,
                source_path=str(tmp_path / "source"),
                uploaded_at="2026-01-01T00:00:00+00:00",
            ),
        ),
    )
    assert upload_job_id is not None
    assert store.claim_next_job(job_types=("upload",)) is not None
    active = store.ensure_active_generation(
        user_id="u1", collection_name="personal",
        embedding_fingerprint="embedding", chunk_fingerprint="chunk",
        index_fingerprint="index", locator_schema_version="locator",
    )
    store.execute(
        """
        UPDATE personal_knowledge_base_jobs
        SET status = 'cancelled', stage = 'cancelled', completed_at = updated_at
        WHERE user_id = 'u1' AND job_id = ?
        """,
        (upload_job_id,),
    )
    store.execute(
        """
        UPDATE personal_knowledge_base_mutations
        SET status = 'failed'
        WHERE user_id = 'u1' AND target_revision = 1
        """
    )
    rebuild_job_id = store.queue_rebuild("u1")
    assert rebuild_job_id is not None
    rebuild = store.claim_next_job(job_types=("rebuild",))
    assert rebuild is not None
    staging = store.begin_rebuild_generation(
        user_id="u1", job_id=rebuild_job_id,
        target_revision=int(rebuild["target_revision"]), file_ids=(file_id,),
        collection_name="personal", embedding_fingerprint="embedding",
        chunk_fingerprint="chunk", index_fingerprint="index",
        locator_schema_version="locator",
    )

    assert store.cancel_rebuild_job(
        user_id="u1", job_id=rebuild_job_id,
        target_revision=int(rebuild["target_revision"]),
        generation_id=staging, reason="input changed",
    )

    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT status FROM personal_knowledge_base_generations WHERE generation_id = ?",
            (staging,),
        ).fetchone() == ("failed",)
        assert connection.execute(
            "SELECT active_generation_id, building_generation_id FROM personal_knowledge_bases WHERE user_id = 'u1'"
        ).fetchone() == (active, None)
    finally:
        connection.close()

def test_display_error_redacts_paths_tokens_and_url_credentials():
    safe = PersonalKnowledgeBaseStore._error(
        "Bearer secret.token failed at /persistent/private/source.pdf "
        "via https://user:password@qdrant.example"
    )
    assert safe is not None
    assert "secret.token" not in safe
    assert "/persistent/private" not in safe
    assert "user:password" not in safe
