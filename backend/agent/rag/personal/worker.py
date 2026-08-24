"""Restart-safe in-process wakeup workers for durable personal-KB jobs."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from backend.core.stores.personal_knowledge_base_store import PersonalKnowledgeBaseStore


logger = logging.getLogger(__name__)


class UploadJobProcessor(Protocol):
    job_types: tuple[str, ...]

    async def process(self, job: dict) -> None: ...


class PersonalKnowledgeBaseWorker:
    """Use asyncio only as a wakeup layer; SQLite remains the task authority."""

    def __init__(
        self,
        store: PersonalKnowledgeBaseStore,
        processor: UploadJobProcessor,
        *,
        worker_count: int,
        max_retries: int,
    ) -> None:
        if worker_count <= 0:
            raise ValueError("worker_count must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self.store = store
        self.processor = processor
        self.worker_count = worker_count
        self.max_retries = max_retries
        self._wake = asyncio.Event()
        self._stopping = False
        self._tasks: list[asyncio.Task[None]] = []

    def start(self) -> int:
        """Recover interrupted claims and start consumers in the background."""

        if self._tasks:
            return 0
        recovered = self.store.recover_running_jobs()
        revision_lag = self.store.has_revision_lag()
        self.store.mark_collection_ready(
            ready=not revision_lag,
            error=(
                "personal revision reconciliation is in progress"
                if revision_lag
                else None
            ),
        )
        self._stopping = False
        self._tasks = [
            asyncio.create_task(self._run(), name=f"personal-kb-worker-{index}")
            for index in range(self.worker_count)
        ]
        self.notify()
        return recovered

    async def reconcile_startup(self) -> tuple[int, bool]:
        """Replay interrupted jobs before personal retrieval becomes ready."""

        if self._tasks:
            raise RuntimeError("startup reconcile must run before worker start")
        recovered = await asyncio.to_thread(self.store.recover_running_jobs)
        if recovered or await asyncio.to_thread(self.store.has_revision_lag):
            await asyncio.to_thread(
                self.store.mark_collection_ready,
                ready=False,
                error="personal revision reconciliation is in progress",
            )
        while True:
            job = await asyncio.to_thread(
                self.store.claim_next_job,
                job_types=getattr(self.processor, "job_types", ("upload",)),
            )
            if job is None:
                break
            await self._process_claimed_job(job)
        reconciled = not await asyncio.to_thread(self.store.has_revision_lag)
        await asyncio.to_thread(
            self.store.mark_collection_ready,
            ready=reconciled,
            error=None if reconciled else (
                "personal revision reconciliation requires explicit retry"
            ),
        )
        return recovered, reconciled

    def notify(self) -> None:
        """Wake idle consumers after a transaction has durably queued work."""

        self._wake.set()

    async def stop(self) -> None:
        """Stop new claims and let active stage/checkpoint work finish safely."""

        self._stopping = True
        self._wake.set()
        tasks, self._tasks = self._tasks, []
        if tasks:
            await asyncio.gather(*tasks)

    async def _run(self) -> None:
        while not self._stopping:
            job = await asyncio.to_thread(
                self.store.claim_next_job,
                job_types=getattr(self.processor, "job_types", ("upload",)),
            )
            if job is None:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=1.0)
                # Python 3.10 keeps asyncio.TimeoutError distinct from the
                # builtin TimeoutError.  Catch the asyncio exception so an
                # idle poll does not permanently kill every queue consumer.
                except asyncio.TimeoutError:
                    pass
                continue
            await self._process_claimed_job(job)

    async def _process_claimed_job(self, job: dict) -> None:
        try:
            await self.processor.process(job)
        except Exception as exc:
            retry = int(job["attempts"]) <= self.max_retries
            logger.exception(
                "personal knowledge-base job failed job_id=%s retry=%s",
                job["job_id"],
                retry,
            )
            await asyncio.to_thread(
                self.store.fail_job,
                user_id=job["user_id"],
                job_id=job["job_id"],
                error=f"{type(exc).__name__}: {exc}",
                retry=retry,
            )
            if retry:
                self.notify()
        else:
            if not await asyncio.to_thread(self.store.has_revision_lag):
                await asyncio.to_thread(
                    self.store.mark_collection_ready, ready=True, error=None
                )
