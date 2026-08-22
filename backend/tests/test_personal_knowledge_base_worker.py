"""Worker lifecycle regressions for the personal knowledge-base queue."""

from __future__ import annotations

import asyncio

from backend.agent.rag.personal import worker as worker_module
from backend.agent.rag.personal import snapshots as snapshots_module
from backend.agent.rag.personal.snapshots import PersonalQdrantSnapshotManager
from backend.agent.rag.personal.worker import PersonalKnowledgeBaseWorker


class _IdleStore:
    def __init__(self) -> None:
        self.claims = 0
        self.worker: PersonalKnowledgeBaseWorker | None = None

    def recover_running_jobs(self) -> int:
        return 0

    def claim_next_job(self, *, job_types):  # noqa: ANN001, ANN201
        del job_types
        self.claims += 1
        if self.claims == 2:
            assert self.worker is not None
            self.worker._stopping = True
        return None


class _UnusedProcessor:
    job_types = ("upload",)

    async def process(self, job: dict) -> None:
        raise AssertionError(f"idle worker unexpectedly received {job!r}")


class _ImmediateTimeoutAsyncio:
    TimeoutError = asyncio.TimeoutError

    @staticmethod
    async def to_thread(function, /, *args, **kwargs):  # noqa: ANN001, ANN202
        return function(*args, **kwargs)

    @staticmethod
    async def wait_for(awaitable, *, timeout):  # noqa: ANN001, ANN202
        del timeout
        awaitable.close()
        raise asyncio.TimeoutError


def test_idle_timeout_does_not_kill_worker_on_python_310() -> None:
    async def scenario() -> None:
        store = _IdleStore()
        worker = PersonalKnowledgeBaseWorker(
            store,  # type: ignore[arg-type]
            _UnusedProcessor(),
            worker_count=1,
            max_retries=0,
        )
        store.worker = worker
        original_asyncio = worker_module.asyncio
        worker_module.asyncio = _ImmediateTimeoutAsyncio  # type: ignore[assignment]
        try:
            await worker._run()
        finally:
            worker_module.asyncio = original_asyncio
        assert store.claims == 2

    asyncio.run(scenario())


class _ImmediateSnapshotTimeoutAsyncio:
    TimeoutError = asyncio.TimeoutError
    manager: PersonalQdrantSnapshotManager | None = None

    @classmethod
    async def wait_for(cls, awaitable, *, timeout):  # noqa: ANN001, ANN202
        del timeout
        awaitable.close()
        assert cls.manager is not None
        cls.manager._stopping = True
        raise asyncio.TimeoutError


def test_idle_timeout_does_not_kill_snapshot_timer_on_python_310() -> None:
    async def scenario() -> None:
        manager = object.__new__(PersonalQdrantSnapshotManager)
        manager._stopping = False
        manager._wake = asyncio.Event()
        manager.max_delay_seconds = 1
        original_asyncio = snapshots_module.asyncio
        _ImmediateSnapshotTimeoutAsyncio.manager = manager
        snapshots_module.asyncio = _ImmediateSnapshotTimeoutAsyncio  # type: ignore[assignment]
        try:
            await manager._run()
        finally:
            snapshots_module.asyncio = original_asyncio
            _ImmediateSnapshotTimeoutAsyncio.manager = None

    asyncio.run(scenario())
