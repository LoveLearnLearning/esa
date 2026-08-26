"""Authoritative startup rebuild for a missing or unusable personal snapshot."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from backend.agent.rag.indexes import PersonalQdrantIndex
from backend.core.stores.personal_knowledge_base_store import (
    PersonalKnowledgeBaseStore,
)

from .ingestion import LOCATOR_SCHEMA_VERSION, PersonalKnowledgeBaseIngestion


class PersonalJournalReplayUnavailable(RuntimeError):
    """The retained journal cannot prove a continuous restore tail."""


class PersonalCollectionRecovery:
    """Recreate committed visible points from SQLite and durable sources."""

    def __init__(
        self,
        *,
        store: PersonalKnowledgeBaseStore,
        ingestion: PersonalKnowledgeBaseIngestion,
        embedding: Any,
        index: PersonalQdrantIndex,
        dense_dimension: int,
        embedding_fingerprint: str,
        embedding_semaphore: asyncio.Semaphore,
        mutation_lock: asyncio.Lock,
    ) -> None:
        self.store = store
        self.ingestion = ingestion
        self.embedding = embedding
        self.index = index
        self.dense_dimension = dense_dimension
        self.embedding_fingerprint = embedding_fingerprint
        self.embedding_semaphore = embedding_semaphore
        self.mutation_lock = mutation_lock

    async def rebuild(self) -> int:
        """Fail closed unless every committed file is reconstructed exactly."""

        authority = await asyncio.to_thread(
            self.store.list_collection_rebuild_authority
        )
        self._validate_fingerprints(authority)
        prepared: list[tuple[dict[str, Any], Any, list[list[float]]]] = []
        for record in authority:
            ingested = await self.ingestion.ingest(
                file_id=record["file_id"],
                filename=record["filename"],
                media_type=record["media_type"],
                source_path=record["source_path"],
                source_sha256=record["sha256"],
            )
            chunks = ingested.chunks.chunks
            embed_documents = getattr(
                self.embedding, "embed_documents", self.embedding.embed
            )
            async with self.embedding_semaphore:
                vectors = await asyncio.to_thread(
                    embed_documents, [chunk.dense_text for chunk in chunks]
                )
            self._validate_vectors(vectors, len(chunks))
            if len(chunks) != int(record["index_count"]):
                raise RuntimeError(
                    "authority rebuild chunk count differs from committed SQLite count"
                )
            prepared.append((record, chunks, vectors))

        # No worker or public readiness exists yet during startup. Holding the
        # same lock nevertheless makes the maintenance boundary explicit.
        async with self.mutation_lock:
            current = await asyncio.to_thread(
                self.store.list_collection_rebuild_authority
            )
            if self._identity(current) != self._identity(authority):
                raise RuntimeError("personal rebuild authority changed during startup")
            await asyncio.to_thread(self.index.ensure_collection, self.dense_dimension)
            await asyncio.to_thread(self.index.maintenance_delete_personal_scope)
            expected_by_tenant: dict[tuple[str, str], int] = defaultdict(int)
            for record, chunks, vectors in prepared:
                await asyncio.to_thread(
                    self.index.upsert_hidden,
                    chunks,
                    vectors,
                    user_id=record["user_id"],
                    knowledge_base_id=record["knowledge_base_id"],
                    file_id=record["file_id"],
                    generation_id=record["generation_id"],
                    ingestion_revision=int(record["ingestion_revision"]),
                )
                hidden = await asyncio.to_thread(
                    self.index.count,
                    user_id=record["user_id"],
                    generation_id=record["generation_id"],
                    knowledge_base_id=record["knowledge_base_id"],
                    file_id=record["file_id"],
                    visible=False,
                )
                if hidden != len(chunks):
                    raise RuntimeError("authority rebuild hidden count mismatch")
                await asyncio.to_thread(
                    self.index.set_file_visibility,
                    user_id=record["user_id"],
                    knowledge_base_id=record["knowledge_base_id"],
                    file_id=record["file_id"],
                    generation_id=record["generation_id"],
                    visible=True,
                )
                expected_by_tenant[
                    (record["user_id"], record["generation_id"])
                ] += len(chunks)
            for (user_id, generation_id), expected in expected_by_tenant.items():
                actual = await asyncio.to_thread(
                    self.index.count,
                    user_id=user_id,
                    generation_id=generation_id,
                    visible=True,
                )
                if actual != expected:
                    raise RuntimeError("authority rebuild generation count mismatch")
            total = await asyncio.to_thread(self.index.maintenance_count_personal)
            if total != sum(expected_by_tenant.values()):
                raise RuntimeError("authority rebuild collection count mismatch")
            await asyncio.to_thread(self.store.mark_collection_rebuilt)
            return total

    async def replay_from(self, restore_cursor: int) -> int:
        """Validate the ordered journal tail, then reconcile authoritative state.

        Superseded operations are deliberately collapsed by the final rebuild:
        this is required when a later delete has already removed an earlier
        upload's source artifacts. Sequence validation still proves that no
        durable mutation between the snapshot and SQLite high-water is lost.
        """

        state = await asyncio.to_thread(self.store.get_collection_state)
        if state is None:
            raise PersonalJournalReplayUnavailable(
                "personal collection state is missing during replay"
            )
        high_water = int(state["qdrant_mutation_seq"])
        if not 0 <= restore_cursor < high_water:
            raise ValueError("restore cursor must be below SQLite high-water")
        mutations = await asyncio.to_thread(
            self.store.list_applied_mutations_after, restore_cursor
        )
        expected_sequences = list(range(restore_cursor + 1, high_water + 1))
        actual_sequences = [
            int(value["qdrant_mutation_seq"]) for value in mutations
        ]
        if actual_sequences != expected_sequences:
            raise PersonalJournalReplayUnavailable(
                "personal mutation journal has a sequence gap"
            )
        allowed_operations = {
            "publish_file", "hide_file", "delete_file",
            "activate_generation", "delete_generation", "delete_user",
        }
        for mutation in mutations:
            if mutation["operation"] not in allowed_operations:
                raise PersonalJournalReplayUnavailable(
                    "personal mutation journal operation is unknown"
                )
            if not mutation["user_id"] or not isinstance(mutation["payload"], dict):
                raise PersonalJournalReplayUnavailable(
                    "personal mutation journal payload is invalid"
                )
        # Reconstructing the current authority is the idempotent replay result.
        # It safely handles histories where earlier source artifacts were
        # intentionally destroyed by a later, sequenced privacy deletion.
        return await self.rebuild()

    def _validate_fingerprints(self, records: list[dict[str, Any]]) -> None:
        for record in records:
            if record["embedding_fingerprint"] != self.embedding_fingerprint:
                raise RuntimeError("active generation embedding fingerprint changed")
            if record["chunk_fingerprint"] != self.ingestion.pipeline_fingerprint:
                raise RuntimeError("active generation ingestion fingerprint changed")
            if record["index_fingerprint"] != self.index.configuration_fingerprint:
                raise RuntimeError("active generation index fingerprint changed")
            if record["locator_schema_version"] != LOCATOR_SCHEMA_VERSION:
                raise RuntimeError("active generation locator schema changed")

    def _validate_vectors(
        self, vectors: list[list[float]], expected_count: int
    ) -> None:
        if len(vectors) != expected_count:
            raise RuntimeError("authority rebuild embedding count mismatch")
        if any(len(vector) != self.dense_dimension for vector in vectors):
            raise RuntimeError("authority rebuild embedding dimension mismatch")
        if any(
            not isinstance(value, (int, float))
            for vector in vectors
            for value in vector
        ):
            raise RuntimeError("authority rebuild embedding contains non-numeric value")

    @staticmethod
    def _identity(records: list[dict[str, Any]]) -> tuple[tuple[Any, ...], ...]:
        return tuple(
            (
                record["user_id"], record["knowledge_base_id"],
                record["generation_id"], record["file_id"],
                record["sha256"], record["ingestion_revision"],
                record["index_count"],
            )
            for record in records
        )
