from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from backend.agent.rag.inference import HashingEmbeddingProvider
from backend.agent.rag.personal import (
    LOCATOR_SCHEMA_VERSION,
    PersonalCollectionRecovery,
    PersonalJournalReplayUnavailable,
    PersonalKnowledgeBaseIngestion,
)


class _UnusedMinerU:
    configuration_fingerprint = "f" * 64

    def parse(self, _source: Path, _output_root: Path):
        raise AssertionError("TXT must use native ingestion")


class _Store:
    def __init__(self, records: list[dict]) -> None:
        self.records = records
        self.rebuilt = False

    def list_collection_rebuild_authority(self) -> list[dict]:
        return [dict(value) for value in self.records]

    def mark_collection_rebuilt(self) -> None:
        self.rebuilt = True


class _ReplayStore(_Store):
    def __init__(self, sequences: list[int]) -> None:
        super().__init__([])
        self.sequences = sequences

    def get_collection_state(self) -> dict:
        return {"qdrant_mutation_seq": 7}

    def list_applied_mutations_after(self, cursor: int) -> list[dict]:
        return [
            {
                "qdrant_mutation_seq": sequence,
                "operation": "publish_file",
                "user_id": "u1",
                "payload": {"file_ids": ["f1"]},
            }
            for sequence in self.sequences
            if sequence > cursor
        ]


class _Index:
    collection = "personal"
    configuration_fingerprint = "index-fingerprint"

    def __init__(self) -> None:
        self.points: dict[tuple[str, str, str], tuple[int, bool]] = {}
        self.recreated = 0

    def maintenance_recreate_collection(self, dense_dimension: int) -> None:
        assert dense_dimension == 8
        self.recreated += 1
        self.points.clear()

    def ensure_collection(self, dense_dimension: int) -> None:
        assert dense_dimension == 8

    def maintenance_delete_personal_scope(self) -> None:
        self.recreated += 1
        self.points.clear()

    def upsert_hidden(
        self, chunks, vectors, *, user_id, knowledge_base_id, file_id, generation_id,
        ingestion_revision,
    ) -> None:
        assert len(chunks) == len(vectors)
        assert ingestion_revision == 4
        self.points[(user_id, generation_id, file_id)] = (len(chunks), False)

    def count(
        self, *, user_id, generation_id, knowledge_base_id=None,
        file_id=None, visible=True
    ) -> int:
        return sum(
            count
            for (point_user, point_generation, point_file), (count, is_visible)
            in self.points.items()
            if point_user == user_id
            and point_generation == generation_id
            and (file_id is None or point_file == file_id)
            and (visible is None or is_visible == visible)
        )

    def set_file_visibility(
        self, *, user_id, knowledge_base_id=None, file_id, generation_id, visible
    ) -> None:
        key = (user_id, generation_id, file_id)
        count, _old = self.points[key]
        self.points[key] = (count, visible)

    def maintenance_count_all(self) -> int:
        return sum(count for count, _visible in self.points.values())

    def maintenance_count_personal(self) -> int:
        return self.maintenance_count_all()


def test_authority_rebuild_recreates_only_committed_visible_points(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("Persistent personal knowledge.\n", encoding="utf-8")
    ingestion = PersonalKnowledgeBaseIngestion(
        tmp_path / "artifacts", mineru_parser=_UnusedMinerU()
    )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    ingested = asyncio.run(
        ingestion.ingest(
            file_id="12345678-1234-5678-1234-567812345678",
            filename="notes.txt",
            media_type="text/plain",
            source_path=source,
            source_sha256=digest,
        )
    )
    records = [
        {
            "user_id": "u1",
            "knowledge_base_id": "kb1",
            "generation_id": "g1",
            "embedding_fingerprint": "embedding-fingerprint",
            "chunk_fingerprint": ingestion.pipeline_fingerprint,
            "index_fingerprint": "index-fingerprint",
            "locator_schema_version": LOCATOR_SCHEMA_VERSION,
            "file_id": "12345678-1234-5678-1234-567812345678",
            "filename": "notes.txt",
            "media_type": "text/plain",
            "sha256": digest,
            "source_path": str(source),
            "ingestion_revision": 4,
            "index_count": len(ingested.chunks.chunks),
        }
    ]
    store = _Store(records)
    index = _Index()
    recovery = PersonalCollectionRecovery(
        store=store,  # type: ignore[arg-type]
        ingestion=ingestion,
        embedding=HashingEmbeddingProvider(dimensions=8),
        index=index,  # type: ignore[arg-type]
        dense_dimension=8,
        embedding_fingerprint="embedding-fingerprint",
        embedding_semaphore=asyncio.Semaphore(1),
        mutation_lock=asyncio.Lock(),
    )

    total = asyncio.run(recovery.rebuild())

    assert total == len(ingested.chunks.chunks)
    assert index.recreated == 1
    assert index.points[("u1", "g1", records[0]["file_id"])][1] is True
    assert store.rebuilt is True

    records[0]["locator_schema_version"] = "personal-locator-obsolete"
    with pytest.raises(RuntimeError, match="locator schema changed"):
        asyncio.run(recovery.rebuild())


def _replay_recovery(store: _ReplayStore) -> PersonalCollectionRecovery:
    recovery = PersonalCollectionRecovery(
        store=store,  # type: ignore[arg-type]
        ingestion=object(),  # type: ignore[arg-type]
        embedding=object(),
        index=object(),  # type: ignore[arg-type]
        dense_dimension=8,
        embedding_fingerprint="embedding-fingerprint",
        embedding_semaphore=asyncio.Semaphore(1),
        mutation_lock=asyncio.Lock(),
    )

    async def rebuilt() -> int:
        store.rebuilt = True
        return 23

    recovery.rebuild = rebuilt  # type: ignore[method-assign]
    return recovery


def test_replay_validates_continuous_tail_without_rewinding_high_water() -> None:
    store = _ReplayStore([6, 7])

    total = asyncio.run(_replay_recovery(store).replay_from(5))

    assert total == 23
    assert store.rebuilt is True
    assert store.get_collection_state()["qdrant_mutation_seq"] == 7


def test_replay_rejects_journal_gap_before_rebuilding() -> None:
    store = _ReplayStore([7])

    try:
        asyncio.run(_replay_recovery(store).replay_from(5))
    except PersonalJournalReplayUnavailable as exc:
        assert "sequence gap" in str(exc)
    else:
        raise AssertionError("journal gap must force authoritative fallback")

    assert store.rebuilt is False
