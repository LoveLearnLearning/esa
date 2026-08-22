"""Dispatch ordered upload and delete mutations for one personal collection."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from backend.agent.rag.indexes import PersonalQdrantIndex
from backend.core.stores.personal_knowledge_base_store import (
    IndexedPersonalKnowledgeBaseFile,
    PersonalKnowledgeBaseStore,
)

from .ingestion import LOCATOR_SCHEMA_VERSION, PersonalKnowledgeBaseIngestion
from .pipeline import PersonalUploadPipeline


class PersonalKnowledgeBaseMutationPipeline:
    """Execute supported mutation types without weakening their tenant filters."""

    job_types = ("upload", "delete", "rebuild", "cleanup_generation")

    def __init__(
        self,
        *,
        upload: PersonalUploadPipeline,
        store: PersonalKnowledgeBaseStore,
        ingestion: PersonalKnowledgeBaseIngestion,
        index: PersonalQdrantIndex,
        mutation_lock: asyncio.Lock,
        discard_source: Callable[[str], None],
        notify_snapshot: Callable[[], None] | None = None,
    ) -> None:
        self.upload = upload
        self.store = store
        self.ingestion = ingestion
        self.index = index
        self.mutation_lock = mutation_lock
        self.discard_source = discard_source
        self.notify_snapshot = notify_snapshot

    async def process(self, job: dict[str, Any]) -> None:
        if job["job_type"] == "upload":
            await self.upload.process(job)
            self._notify_snapshot()
            return
        if job["job_type"] == "delete":
            await self._delete(job)
            self._notify_snapshot()
            return
        if job["job_type"] == "rebuild":
            await self._rebuild(job)
            self._notify_snapshot()
            return
        if job["job_type"] == "cleanup_generation":
            await self._cleanup_generation(job)
            self._notify_snapshot()
            return
        raise ValueError(f"unsupported personal mutation job: {job['job_type']}")

    def _notify_snapshot(self) -> None:
        if self.notify_snapshot is not None:
            self.notify_snapshot()

    async def _delete(self, job: dict[str, Any]) -> None:
        user_id = str(job["user_id"])
        job_id = str(job["job_id"])
        target_revision = int(job["target_revision"])
        file_id = str(job["payload"].get("file_id", ""))
        if not file_id:
            raise ValueError("delete job has no file_id")
        self.store.update_job_progress(
            user_id=user_id, job_id=job_id, progress=0.10, stage="deleting"
        )
        record = self.store.get_tombstoned_file(user_id=user_id, file_id=file_id)
        if record is None:
            raise RuntimeError("delete tombstone is missing or already cleaned")
        if not self.store.mark_mutation_applying(
            user_id=user_id,
            target_revision=target_revision,
            operation="delete_file",
        ):
            raise RuntimeError("delete mutation is not apply eligible")
        generation_ids = self.store.list_generation_ids(user_id)
        async with self.mutation_lock:
            for generation_id in generation_ids:
                await asyncio.to_thread(
                    self.index.set_file_visibility,
                    user_id=user_id,
                    file_id=file_id,
                    generation_id=generation_id,
                    visible=False,
                )
                await asyncio.to_thread(
                    self.index.delete_file,
                    user_id=user_id,
                    file_id=file_id,
                    generation_id=generation_id,
                )
                self.store.update_job_progress(
                    user_id=user_id, job_id=job_id, progress=0.70,
                    stage="verifying",
                )
                remaining = await asyncio.to_thread(
                    self.index.count,
                    user_id=user_id,
                    generation_id=generation_id,
                    file_id=file_id,
                    visible=None,
                )
                if remaining != 0:
                    raise RuntimeError("Qdrant file deletion verification failed")
            # Source and derived artifact removal is idempotent. It happens
            # before the SQLite commit so a crash can safely replay deletion.
            await asyncio.to_thread(self.discard_source, file_id)
            await asyncio.to_thread(self.ingestion.discard_file_artifacts, file_id)
            self.store.update_job_progress(
                user_id=user_id, job_id=job_id, progress=0.95,
                stage="committing",
            )
            await asyncio.to_thread(
                self.store.commit_delete_index,
                user_id=user_id,
                job_id=job_id,
                target_revision=target_revision,
                collection_name=self.index.collection,
                file_id=file_id,
            )

    async def _rebuild(self, job: dict[str, Any]) -> None:
        user_id = str(job["user_id"])
        job_id = str(job["job_id"])
        target_revision = int(job["target_revision"])
        file_ids = [str(value) for value in job["payload"].get("file_ids", [])]
        records = self.store.get_job_files(user_id=user_id, file_ids=file_ids)
        if [item["file_id"] for item in records] != file_ids:
            self.store.cancel_rebuild_job(
                user_id=user_id,
                job_id=job_id,
                target_revision=target_revision,
                generation_id=None,
                reason="rebuild input changed before staging",
            )
            return
        await asyncio.to_thread(
            self.index.ensure_collection, self.upload.dense_dimension
        )
        generation_id = self.store.begin_rebuild_generation(
            user_id=user_id,
            job_id=job_id,
            target_revision=target_revision,
            file_ids=file_ids,
            collection_name=self.index.collection,
            embedding_fingerprint=self.upload.embedding_fingerprint,
            chunk_fingerprint=self.ingestion.pipeline_fingerprint,
            index_fingerprint=self.index.configuration_fingerprint,
            locator_schema_version=LOCATOR_SCHEMA_VERSION,
        )
        indexed: list[IndexedPersonalKnowledgeBaseFile] = []
        for position, record in enumerate(records):
            base = position / len(records)
            self.store.update_job_progress(
                user_id=user_id, job_id=job_id,
                progress=0.05 + 0.10 * base, stage="parsing",
                file_ids=(record["file_id"],),
            )
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
                break
            chunks = result.chunks.chunks
            self.store.update_job_progress(
                user_id=user_id, job_id=job_id,
                progress=0.15 + 0.20 * base, stage="chunking",
                file_ids=(record["file_id"],),
            )
            self.store.update_job_progress(
                user_id=user_id, job_id=job_id,
                progress=0.35 + 0.15 * base, stage="embedding",
                file_ids=(record["file_id"],),
            )
            embed_documents = getattr(
                self.upload.embedding,
                "embed_documents",
                self.upload.embedding.embed,
            )
            async with self.upload.embedding_semaphore:
                vectors = await asyncio.to_thread(
                    embed_documents, [chunk.dense_text for chunk in chunks]
                )
            self.upload._validate_vectors(vectors, len(chunks))
            if not self.store.get_job_files(
                user_id=user_id, file_ids=(record["file_id"],)
            ):
                break
            self.store.update_job_progress(
                user_id=user_id, job_id=job_id,
                progress=0.50 + 0.15 * base, stage="indexing",
                file_ids=(record["file_id"],),
            )
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
                ingestion_revision=target_revision,
            )
            self.store.update_job_progress(
                user_id=user_id, job_id=job_id,
                progress=0.65 + 0.15 * base, stage="verifying",
                file_ids=(record["file_id"],),
            )
            hidden = await asyncio.to_thread(
                self.index.count,
                user_id=user_id,
                generation_id=generation_id,
                file_id=record["file_id"],
                visible=False,
            )
            if hidden != len(chunks):
                raise RuntimeError("rebuild hidden point verification failed")
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
                progress=0.10 + 0.75 * ((position + 1) / len(records)),
                stage="verifying",
                file_ids=(record["file_id"],),
            )
        if not self.store.mark_mutation_applying(
            user_id=user_id,
            target_revision=target_revision,
            operation="activate_generation",
        ):
            raise RuntimeError("rebuild mutation is not apply eligible")
        async with self.mutation_lock:
            live = self.store.get_job_files(user_id=user_id, file_ids=file_ids)
            if [item["file_id"] for item in live] != file_ids:
                await asyncio.to_thread(
                    self.index.delete_generation,
                    user_id=user_id,
                    generation_id=generation_id,
                )
                remaining = await asyncio.to_thread(
                    self.index.count,
                    user_id=user_id,
                    generation_id=generation_id,
                    visible=None,
                )
                if remaining != 0:
                    raise RuntimeError(
                        "cancelled rebuild staging cleanup verification failed"
                    )
                await asyncio.to_thread(
                    self.store.cancel_rebuild_job,
                    user_id=user_id,
                    job_id=job_id,
                    target_revision=target_revision,
                    generation_id=generation_id,
                    reason="rebuild input changed before activation",
                )
                return
            for item in indexed:
                await asyncio.to_thread(
                    self.index.set_file_visibility,
                    user_id=user_id,
                    file_id=item.file_id,
                    generation_id=generation_id,
                    visible=True,
                )
            visible = await asyncio.to_thread(
                self.index.count,
                user_id=user_id,
                generation_id=generation_id,
                visible=True,
            )
            if visible != sum(item.index_count for item in indexed):
                raise RuntimeError("rebuild visible generation verification failed")
            self.store.update_job_progress(
                user_id=user_id, job_id=job_id, progress=0.95,
                stage="committing",
            )
            await asyncio.to_thread(
                self.store.commit_rebuild_job,
                user_id=user_id,
                job_id=job_id,
                target_revision=target_revision,
                generation_id=generation_id,
                collection_name=self.index.collection,
                files=indexed,
            )

    async def _cleanup_generation(self, job: dict[str, Any]) -> None:
        user_id = str(job["user_id"])
        job_id = str(job["job_id"])
        target_revision = int(job["target_revision"])
        generation_id = str(job["payload"].get("generation_id", ""))
        if not generation_id:
            raise ValueError("generation cleanup has no generation_id")
        self.store.update_job_progress(
            user_id=user_id, job_id=job_id, progress=0.20, stage="cleaning"
        )
        if not self.store.mark_mutation_applying(
            user_id=user_id,
            target_revision=target_revision,
            operation="delete_generation",
        ):
            raise RuntimeError("generation cleanup mutation is not apply eligible")
        async with self.mutation_lock:
            await asyncio.to_thread(
                self.index.delete_generation,
                user_id=user_id,
                generation_id=generation_id,
            )
            remaining = await asyncio.to_thread(
                self.index.count,
                user_id=user_id,
                generation_id=generation_id,
                visible=None,
            )
            if remaining != 0:
                raise RuntimeError("retired generation deletion verification failed")
            self.store.update_job_progress(
                user_id=user_id, job_id=job_id, progress=0.90,
                stage="committing",
            )
            await asyncio.to_thread(
                self.store.commit_generation_cleanup,
                user_id=user_id,
                job_id=job_id,
                target_revision=target_revision,
                generation_id=generation_id,
                collection_name=self.index.collection,
            )
