"""End-to-end upload pipeline test with real DocIR/Chunk and fake Qdrant."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from pathlib import Path

import pytest

from backend.agent.rag.inference import HashingEmbeddingProvider
from backend.agent.rag.personal import (
    PersonalCollectionRecovery,
    PersonalKnowledgeBaseIngestion,
    PersonalKnowledgeBaseMutationPipeline,
    PersonalKnowledgeRetrievalService,
    PersonalUploadPipeline,
)
from backend.core.stores.migrations import run_migrations
from backend.core.stores.personal_knowledge_base_store import (
    NewPersonalKnowledgeBaseFile,
    PersonalKnowledgeBaseStore,
)
from backend.core.stores.user_store import UserStore


class _UnusedMinerU:
    configuration_fingerprint = "f" * 64

    def parse(self, _source: Path, _output_root: Path):
        raise AssertionError("TXT must use native ingestion")


class _FakePersonalIndex:
    collection = "personal-test"
    configuration_fingerprint = "e" * 64

    def __init__(self):
        self.points: dict[tuple[str, str, str], tuple[int, bool]] = {}
        self.chunk_payloads: dict[tuple[str, str, str], list[dict]] = {}
        self.dense_name = "dense"
        self.body_name = "bm25_body"
        self.heading_name = "bm25_heading"

    def ensure_collection(self, dense_dimension: int) -> None:
        assert dense_dimension == 8

    def maintenance_recreate_collection(self, dense_dimension: int) -> None:
        assert dense_dimension == 8
        self.points.clear()
        self.chunk_payloads.clear()

    def maintenance_count_all(self) -> int:
        return sum(count for count, _visible in self.points.values())

    def set_file_visibility(
        self, *, user_id, file_id, generation_id, visible
    ) -> None:
        key = (user_id, generation_id, file_id)
        if key in self.points:
            count, _old = self.points[key]
            self.points[key] = (count, visible)

    def upsert_hidden(
        self, chunks, vectors, *, user_id, file_id, generation_id,
        ingestion_revision,
    ) -> None:
        assert len(chunks) == len(vectors)
        assert ingestion_revision > 0
        key = (user_id, generation_id, file_id)
        self.points[key] = (len(chunks), False)
        self.chunk_payloads[key] = [
            chunk.model_dump(mode="json") for chunk in chunks
        ]

    def count(
        self, *, user_id, generation_id, file_id=None, visible=True
    ) -> int:
        total = 0
        for (point_user, point_generation, point_file), (count, is_visible) in (
            self.points.items()
        ):
            if point_user != user_id or point_generation != generation_id:
                continue
            if file_id is not None and point_file != file_id:
                continue
            if visible is not None and visible != is_visible:
                continue
            total += count
        return total

    def delete_file(self, *, user_id, file_id, generation_id) -> None:
        key = (user_id, generation_id, file_id)
        self.points.pop(key, None)
        self.chunk_payloads.pop(key, None)

    def delete_generation(self, *, user_id, generation_id) -> None:
        for key in list(self.points):
            if key[0] == user_id and key[1] == generation_id:
                self.points.pop(key)
                self.chunk_payloads.pop(key, None)

    @staticmethod
    def bm25_query(text: str) -> dict:
        return {"text": text}

    def query_points(
        self, _query, _using, limit, *, user_id, generation_id, file_ids
    ) -> list[dict]:
        results = []
        for key, (_count, visible) in self.points.items():
            point_user, point_generation, point_file = key
            if (
                not visible
                or point_user != user_id
                or point_generation != generation_id
                or point_file not in file_ids
            ):
                continue
            for chunk in self.chunk_payloads[key]:
                results.append(
                    {
                        "chunk_id": chunk["chunk_id"],
                        "file_id": point_file,
                        "score": 1.0,
                        "payload": {
                            **chunk,
                            "scope": "personal",
                            "user_id": user_id,
                            "file_id": point_file,
                        },
                    }
                )
        return results[:limit]


def test_upload_pipeline_reaches_ready_only_after_visible_count(tmp_path):
    database = tmp_path / "user.db"
    UserStore(database)
    run_migrations(database)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO users (id, username, password_hash) VALUES ('u1', 'alice', 'hash')"
    )
    connection.commit()
    connection.close()
    source = tmp_path / "source.txt"
    source.write_text(
        "Dijkstra computes shortest paths from one source in a weighted graph.",
        encoding="utf-8",
    )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = PersonalKnowledgeBaseStore(database)
    _ids, job_id = store.create_upload(
        user_id="u1",
        files=(
            NewPersonalKnowledgeBaseFile(
                file_id="12345678-1234-5678-1234-567812345678",
                filename="notes.txt",
                suffix=".txt",
                media_type="text/plain",
                size_bytes=source.stat().st_size,
                sha256=digest,
                source_path=str(source),
                uploaded_at="2026-08-21T00:00:00+00:00",
            ),
        ),
    )
    assert job_id is not None
    job = store.claim_next_job(job_types=("upload",))
    assert job is not None
    index = _FakePersonalIndex()
    pipeline = PersonalUploadPipeline(
        store=store,
        ingestion=PersonalKnowledgeBaseIngestion(
            tmp_path / "artifacts", mineru_parser=_UnusedMinerU()
        ),
        embedding=HashingEmbeddingProvider(dimensions=8),
        index=index,  # type: ignore[arg-type]
        dense_dimension=8,
        embedding_semaphore=asyncio.Semaphore(1),
        mutation_lock=asyncio.Lock(),
    )
    asyncio.run(pipeline.process(job))
    snapshot = store.get_snapshot("u1")
    assert snapshot["status"] == "ready"
    assert snapshot["progress"] == 1.0
    assert snapshot["chunk_count"] == snapshot["index_count"] > 0
    assert snapshot["files"][0]["status"] == "ready"
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT qdrant_mutation_seq FROM personal_knowledge_base_collection_state"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT status FROM personal_knowledge_base_mutations"
        ).fetchone() == ("applied",)
        assert connection.execute(
            "SELECT desired_revision, indexed_revision FROM personal_knowledge_bases WHERE user_id = 'u1'"
        ).fetchone() == (1, 1)
        assert connection.execute(
            """
            SELECT qdrant_mutation_seq, snapshot_mutation_seq
            FROM personal_knowledge_base_collection_state
            """
        ).fetchone() == (1, 0)
    finally:
        connection.close()

    def discard_source(_file_id: str) -> None:
        source.unlink(missing_ok=True)

    mutations = PersonalKnowledgeBaseMutationPipeline(
        upload=pipeline,
        store=store,
        ingestion=pipeline.ingestion,
        index=index,  # type: ignore[arg-type]
        mutation_lock=pipeline.mutation_lock,
        discard_source=discard_source,
    )
    active_before = store.get_retrieval_state("u1")["generation_id"]
    assert store.queue_rebuild("u1") is not None
    rebuild_job = store.claim_next_job(job_types=mutations.job_types)
    assert rebuild_job is not None and rebuild_job["job_type"] == "rebuild"
    asyncio.run(mutations.process(rebuild_job))
    cleanup_job = store.claim_next_job(job_types=mutations.job_types)
    assert cleanup_job is not None
    assert cleanup_job["job_type"] == "cleanup_generation"
    asyncio.run(mutations.process(cleanup_job))
    assert store.get_snapshot("u1")["status"] == "ready"
    assert len(index.points) == 1
    active_after = store.get_retrieval_state("u1")["generation_id"]
    assert active_after is not None and active_after != active_before
    assert {key[1] for key in index.points} == {active_after}
    store.mark_collection_ready(ready=True)
    retrieval = PersonalKnowledgeRetrievalService(
        store=store,
        index=index,  # type: ignore[arg-type]
        embedding=HashingEmbeddingProvider(dimensions=8),
        embedding_semaphore=asyncio.Semaphore(1),
    )
    rebuilt_query = asyncio.run(
        retrieval.search(user_id="u1", query="shortest paths", top_k=5)
    )
    assert rebuilt_query["result_count"] > 0
    assert rebuilt_query["results"][0]["source"] == "notes.txt"
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT desired_revision, indexed_revision FROM personal_knowledge_bases WHERE user_id = 'u1'"
        ).fetchone() == (2, 2)
        assert connection.execute(
            """
            SELECT qdrant_mutation_seq, snapshot_mutation_seq
            FROM personal_knowledge_base_collection_state
            """
        ).fetchone() == (3, 0)
    finally:
        connection.close()

    assert store.tombstone_file(
        user_id="u1", file_id="12345678-1234-5678-1234-567812345678"
    )
    delete_job = store.claim_next_job(job_types=mutations.job_types)
    assert delete_job is not None
    asyncio.run(mutations.process(delete_job))
    assert not source.exists()
    deleted_snapshot = store.get_snapshot("u1")
    assert deleted_snapshot["status"] == "idle"
    assert deleted_snapshot["files"] == []
    assert not index.points
    deleted_query = asyncio.run(
        retrieval.search(user_id="u1", query="shortest paths", top_k=5)
    )
    assert deleted_query["result_count"] == 0
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT desired_revision, indexed_revision FROM personal_knowledge_bases WHERE user_id = 'u1'"
        ).fetchone() == (3, 3)
        assert connection.execute(
            "SELECT qdrant_mutation_seq FROM personal_knowledge_base_collection_state"
        ).fetchone() == (4,)
    finally:
        connection.close()

    # Simulate restoring a snapshot from before all four mutations. A stale
    # deleted-file point must disappear, journal high-water must not rewind,
    # and per-user revisions must remain reconciled.
    index.points[
        ("u1", str(active_after), "12345678-1234-5678-1234-567812345678")
    ] = (1, True)
    recovery = PersonalCollectionRecovery(
        store=store,
        ingestion=pipeline.ingestion,
        embedding=pipeline.embedding,
        index=index,  # type: ignore[arg-type]
        dense_dimension=8,
        embedding_fingerprint=pipeline.embedding_fingerprint,
        embedding_semaphore=pipeline.embedding_semaphore,
        mutation_lock=pipeline.mutation_lock,
    )
    assert asyncio.run(recovery.replay_from(0)) == 0
    assert not index.points
    state = store.get_collection_state()
    assert state is not None and state["qdrant_mutation_seq"] == 4
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT desired_revision, indexed_revision FROM personal_knowledge_bases WHERE user_id = 'u1'"
        ).fetchone() == (3, 3)
    finally:
        connection.close()


def test_upload_replays_idempotently_after_qdrant_before_sqlite_crash(tmp_path):
    database = tmp_path / "user.db"
    UserStore(database)
    run_migrations(database)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO users (id, username, password_hash) VALUES ('u1', 'alice', 'hash')"
    )
    connection.commit()
    connection.close()
    source = tmp_path / "source.txt"
    source.write_text("A durable replay fixture.", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = PersonalKnowledgeBaseStore(database)
    file_id = "72345678-1234-5678-1234-567812345678"
    _ids, job_id = store.create_upload(
        user_id="u1",
        files=(
            NewPersonalKnowledgeBaseFile(
                file_id=file_id, filename="notes.txt", suffix=".txt",
                media_type="text/plain", size_bytes=source.stat().st_size,
                sha256=digest, source_path=str(source),
                uploaded_at="2026-08-21T00:00:00+00:00",
            ),
        ),
    )
    assert job_id is not None
    index = _FakePersonalIndex()
    ingestion = PersonalKnowledgeBaseIngestion(
        tmp_path / "artifacts", mineru_parser=_UnusedMinerU()
    )
    pipeline = PersonalUploadPipeline(
        store=store, ingestion=ingestion,
        embedding=HashingEmbeddingProvider(dimensions=8),
        index=index,  # type: ignore[arg-type]
        dense_dimension=8, embedding_semaphore=asyncio.Semaphore(1),
        mutation_lock=asyncio.Lock(),
    )
    first_claim = store.claim_next_job(job_types=("upload",))
    assert first_claim is not None
    upsert = index.upsert_hidden

    def crash_after_partial_upsert(
        chunks, vectors, *, user_id, file_id, generation_id,
        ingestion_revision,
    ):
        upsert(
            chunks, vectors, user_id=user_id, file_id=file_id,
            generation_id=generation_id,
            ingestion_revision=ingestion_revision,
        )
        count, _visible = index.points[(user_id, generation_id, file_id)]
        index.points[(user_id, generation_id, file_id)] = (
            max(1, count - 1), False
        )
        raise RuntimeError("simulated crash during Qdrant upsert")

    index.upsert_hidden = crash_after_partial_upsert  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="during Qdrant upsert"):
        asyncio.run(pipeline.process(first_claim))
    assert index.points
    assert list((tmp_path / "artifacts" / file_id).glob("*/manifest.json"))

    assert store.recover_running_jobs() == 1
    second_claim = store.claim_next_job(job_types=("upload",))
    assert second_claim is not None
    index.upsert_hidden = upsert  # type: ignore[method-assign]
    commit = store.commit_upload_job

    def crash_before_sqlite_commit(**_values):
        raise RuntimeError("simulated crash after Qdrant visibility")

    store.commit_upload_job = crash_before_sqlite_commit  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="simulated crash"):
        asyncio.run(pipeline.process(second_claim))
    state = store.get_collection_state()
    assert state is None or state["qdrant_mutation_seq"] == 0
    assert any(visible for _count, visible in index.points.values())

    assert store.recover_running_jobs() == 1
    replay = store.claim_next_job(job_types=("upload",))
    assert replay is not None
    store.commit_upload_job = commit  # type: ignore[method-assign]
    asyncio.run(pipeline.process(replay))

    state = store.get_collection_state()
    assert state is not None and state["qdrant_mutation_seq"] == 1
    assert store.get_snapshot("u1")["status"] == "ready"
    assert len(index.points) == 1
