"""Ordered upload pipeline from durable sources to visible personal points."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from backend.agent.rag.fingerprints import backend_fingerprint
from backend.agent.rag.indexes import PersonalQdrantIndex
from backend.agent.rag.retrieval.contracts import EmbeddingProvider
from backend.core.stores.personal_knowledge_base_store import (
    IndexedPersonalKnowledgeBaseFile,
    PersonalKnowledgeBaseStore,
)

from .ingestion import LOCATOR_SCHEMA_VERSION, PersonalKnowledgeBaseIngestion


class PersonalUploadPipeline:
    """Build hidden points, verify them, then publish and commit one revision."""

    def __init__(
        self,
        *,
        store: PersonalKnowledgeBaseStore,
        ingestion: PersonalKnowledgeBaseIngestion,
        embedding: EmbeddingProvider,
        index: PersonalQdrantIndex,
        dense_dimension: int,
        embedding_semaphore: asyncio.Semaphore,
        mutation_lock: asyncio.Lock,
    ) -> None:
        if dense_dimension <= 0:
            raise ValueError("dense_dimension must be positive")
        self.store = store
        self.ingestion = ingestion
        self.embedding = embedding
        self.index = index
        self.dense_dimension = dense_dimension
        self.embedding_semaphore = embedding_semaphore
        self.mutation_lock = mutation_lock

    @property
    def embedding_fingerprint(self) -> str:
        return backend_fingerprint(
            self.embedding,
            {
                "backend": type(self.embedding).__qualname__,
                "model_name": self.embedding.model_name,
            },
        )

    async def process(self, job: dict[str, Any]) -> None:
        if job["job_type"] != "upload":
            raise ValueError("PersonalUploadPipeline only accepts upload jobs")
        user_id = str(job["user_id"])
        job_id = str(job["job_id"])
        target_revision = int(job["target_revision"])
        file_ids = [str(value) for value in job["payload"].get("file_ids", [])]
        if not file_ids:
            raise ValueError("upload job has no files")
        await asyncio.to_thread(self.index.ensure_collection, self.dense_dimension)
        generation_id = self.store.ensure_active_generation(
            user_id=user_id,
            collection_name=self.index.collection,
            embedding_fingerprint=self.embedding_fingerprint,
            chunk_fingerprint=self.ingestion.pipeline_fingerprint,
            index_fingerprint=self.index.configuration_fingerprint,
            locator_schema_version=LOCATOR_SCHEMA_VERSION,
        )
        records = self.store.get_job_files(user_id=user_id, file_ids=file_ids)
        if not records:
            if not self.store.cancel_empty_upload_job(
                user_id=user_id,
                job_id=job_id,
                target_revision=target_revision,
            ):
                raise RuntimeError("empty upload job is not cancellation eligible")
            return
        self.store.update_job_progress(
            user_id=user_id, job_id=job_id, progress=0.05,
            stage="parsing", file_ids=file_ids,
        )
        indexed: list[IndexedPersonalKnowledgeBaseFile] = []
        for position, record in enumerate(records):
            base = position / len(records)
            result = await self.ingestion.ingest(
                file_id=record["file_id"],
                filename=record["filename"],
                media_type=record["media_type"],
                source_path=record["source_path"],
                source_sha256=record["sha256"],
            )
            if not self.store.get_job_files(
                user_id=user_id, file_ids=(record["file_id"],)
            ):
                continue
            self.store.update_job_progress(
                user_id=user_id,
                job_id=job_id,
                progress=0.10 + 0.25 * (base + 1 / len(records)),
                stage="chunking",
                file_ids=(record["file_id"],),
            )
            chunks = result.chunks.chunks
            self.store.update_job_progress(
                user_id=user_id,
                job_id=job_id,
                progress=0.35 + 0.10 * base,
                stage="embedding",
                file_ids=(record["file_id"],),
            )
            embed_documents = getattr(
                self.embedding, "embed_documents", self.embedding.embed
            )
            async with self.embedding_semaphore:
                vectors = await asyncio.to_thread(
                    embed_documents, [chunk.dense_text for chunk in chunks]
                )
            self._validate_vectors(vectors, len(chunks))
            if not self.store.get_job_files(
                user_id=user_id, file_ids=(record["file_id"],)
            ):
                continue
            self.store.update_job_progress(
                user_id=user_id,
                job_id=job_id,
                progress=0.45 + 0.15 * base,
                stage="indexing",
                file_ids=(record["file_id"],),
            )
            # A retry first returns every deterministic point to hidden state;
            # no partial/replayed write can accidentally stay searchable.
            await asyncio.to_thread(
                self.index.set_file_visibility,
                user_id=user_id,
                file_id=record["file_id"],
                generation_id=generation_id,
                visible=False,
            )
            await asyncio.to_thread(
                self.index.upsert_hidden,
                chunks,
                vectors,
                user_id=user_id,
                file_id=record["file_id"],
                generation_id=generation_id,
                ingestion_revision=int(record["ingestion_revision"]),
            )
            self.store.update_job_progress(
                user_id=user_id,
                job_id=job_id,
                progress=0.60 + 0.20 * base,
                stage="verifying",
                file_ids=(record["file_id"],),
            )
            hidden_count = await asyncio.to_thread(
                self.index.count,
                user_id=user_id,
                generation_id=generation_id,
                file_id=record["file_id"],
                visible=False,
            )
            if hidden_count != len(chunks):
                raise RuntimeError("Qdrant hidden point verification failed")
            indexed.append(
                IndexedPersonalKnowledgeBaseFile(
                    file_id=record["file_id"],
                    docir_manifest_path=str(result.manifest_path),
                    chunk_manifest_path=str(result.chunk_path),
                    chunk_count=len(chunks),
                    index_count=len(chunks),
                )
            )
            self.store.update_job_progress(
                user_id=user_id,
                job_id=job_id,
                progress=0.45 + 0.40 * (base + 1 / len(records)),
                stage="verifying",
                file_ids=(record["file_id"],),
            )
        if not self.store.mark_mutation_applying(
            user_id=user_id,
            target_revision=target_revision,
            operation="publish_file",
        ):
            raise RuntimeError("upload mutation is not apply eligible")
        async with self.mutation_lock:
            live_ids = {
                item["file_id"]
                for item in self.store.get_job_files(
                    user_id=user_id,
                    file_ids=(item.file_id for item in indexed),
                )
            }
            indexed = [item for item in indexed if item.file_id in live_ids]
            if not indexed:
                if not self.store.cancel_empty_upload_job(
                    user_id=user_id,
                    job_id=job_id,
                    target_revision=target_revision,
                ):
                    raise RuntimeError("upload job is not cancellation eligible")
                return
            for item in indexed:
                await asyncio.to_thread(
                    self.index.set_file_visibility,
                    user_id=user_id,
                    file_id=item.file_id,
                    generation_id=generation_id,
                    visible=True,
                )
                visible_count = await asyncio.to_thread(
                    self.index.count,
                    user_id=user_id,
                    generation_id=generation_id,
                    file_id=item.file_id,
                    visible=True,
                )
                if visible_count != item.index_count:
                    raise RuntimeError("Qdrant visible point verification failed")
            self.store.update_job_progress(
                user_id=user_id, job_id=job_id, progress=0.95,
                stage="committing", file_ids=file_ids,
            )
            self.store.commit_upload_job(
                user_id=user_id,
                job_id=job_id,
                target_revision=target_revision,
                generation_id=generation_id,
                collection_name=self.index.collection,
                files=indexed,
            )

    def _validate_vectors(
        self, vectors: Sequence[Sequence[float]], expected_count: int
    ) -> None:
        if len(vectors) != expected_count:
            raise ValueError("embedding output count does not match chunks")
        if any(len(vector) != self.dense_dimension for vector in vectors):
            raise ValueError("embedding output dimension does not match configuration")
        if any(
            not isinstance(value, (int, float))
            for vector in vectors
            for value in vector
        ):
            raise ValueError("embedding output contains a non-numeric value")
