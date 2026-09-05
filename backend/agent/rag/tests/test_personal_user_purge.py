"""Tenant-wide personal knowledge-base privacy deletion tests."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from backend.agent.rag.personal.purge import PersonalKnowledgeBaseUserPurger
from backend.core.stores.migrations import run_migrations
from backend.core.stores.personal_knowledge_base_store import (
    PersonalKnowledgeBaseConflict,
    PersonalKnowledgeBaseStore,
)
from backend.core.stores.user_store import UserStore


class _Index:
    def __init__(self, *, absent: bool = True) -> None:
        self.absent = absent
        self.deleted: list[str] = []

    def maintenance_delete_user(self, *, user_id: str) -> None:
        self.deleted.append(user_id)

    def maintenance_user_absent(self, *, user_id: str) -> bool:
        assert self.deleted == [user_id]
        return self.absent


def _store(tmp_path) -> PersonalKnowledgeBaseStore:
    database = tmp_path / "user.db"
    UserStore(database)
    run_migrations(database)
    connection = sqlite3.connect(database)
    now = "2026-08-21T00:00:00+00:00"
    connection.execute(
        "INSERT INTO users (id, username, password_hash) VALUES ('u1', 'one', 'hash')"
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
    store = PersonalKnowledgeBaseStore(database)
    store.ensure_collection_state("personal")
    return store


def test_user_purger_deletes_vectors_artifacts_and_flushes_clean_snapshot(
    tmp_path,
):
    store = _store(tmp_path)
    index = _Index()
    discarded_sources: list[str] = []
    discarded_artifacts: list[str] = []

    async def flush() -> bool:
        record = store.get_user_purge("u1")
        assert record is not None and record["status"] == "applied"
        assert store.complete_user_purge(
            purge_id=record["purge_id"],
            qdrant_mutation_seq=record["qdrant_mutation_seq"],
        ) is True
        return True

    purger = PersonalKnowledgeBaseUserPurger(
        store=store,
        index=index,
        mutation_lock=asyncio.Lock(),
        discard_source=discarded_sources.append,
        discard_artifacts=discarded_artifacts.append,
        flush_snapshot=flush,
    )
    result = asyncio.run(purger.purge("u1"))

    assert result["status"] == "completed"
    assert index.deleted == ["u1"]
    assert discarded_sources == ["file-1"]
    assert discarded_artifacts == ["file-1"]
    # Purge completion leaves a durable deny marker so retrieval cannot race
    # with account deletion or accidentally expose stale artifacts.
    with pytest.raises(PersonalKnowledgeBaseConflict, match="scheduled for purge"):
        store.get_retrieval_state("u1")
    assert asyncio.run(purger.purge("u1"))["status"] == "completed"


def test_user_purger_never_commits_when_qdrant_absence_is_unproven(tmp_path):
    store = _store(tmp_path)
    purger = PersonalKnowledgeBaseUserPurger(
        store=store,
        index=_Index(absent=False),
        mutation_lock=asyncio.Lock(),
        discard_source=lambda _file_id: None,
        discard_artifacts=lambda _file_id: None,
    )

    with pytest.raises(RuntimeError, match="verification failed"):
        asyncio.run(purger.purge("u1"))

    record = store.get_user_purge("u1")
    assert record is not None
    assert record["status"] == "failed"
    assert record["qdrant_mutation_seq"] is None
    assert store.get_collection_state()["qdrant_mutation_seq"] == 0
