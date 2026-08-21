from __future__ import annotations

import asyncio

from backend.agent.rag.personal.worker import PersonalKnowledgeBaseWorker


class _Store:
    def __init__(self, jobs: list[dict]) -> None:
        self.jobs = jobs
        self.recovered = 2
        self.lag = bool(jobs)
        self.ready_updates: list[tuple[bool, str | None]] = []

    def recover_running_jobs(self) -> int:
        recovered, self.recovered = self.recovered, 0
        return recovered

    def has_revision_lag(self) -> bool:
        return self.lag

    def mark_collection_ready(
        self, *, ready: bool, error: str | None = None
    ) -> None:
        self.ready_updates.append((ready, error))

    def claim_next_job(self, *, job_types: tuple[str, ...]) -> dict | None:
        assert job_types == ("upload", "delete")
        return self.jobs.pop(0) if self.jobs else None

    def fail_job(
        self, *, user_id: str, job_id: str, error: str, retry: bool
    ) -> bool:
        assert user_id == "u1"
        assert job_id
        assert error
        if retry:
            self.jobs.append(
                {"user_id": user_id, "job_id": job_id, "attempts": 2}
            )
        return True


class _Processor:
    job_types = ("upload", "delete")

    def __init__(self, store: _Store, *, fail: bool = False) -> None:
        self.store = store
        self.fail = fail
        self.seen: list[str] = []

    async def process(self, job: dict) -> None:
        self.seen.append(job["job_id"])
        if self.fail:
            raise RuntimeError("simulated interruption")
        if not self.store.jobs:
            self.store.lag = False


def test_startup_reconcile_drains_recovered_jobs_before_ready() -> None:
    jobs = [
        {"user_id": "u1", "job_id": "j1", "attempts": 1},
        {"user_id": "u1", "job_id": "j2", "attempts": 1},
    ]
    store = _Store(jobs)
    processor = _Processor(store)
    worker = PersonalKnowledgeBaseWorker(
        store,  # type: ignore[arg-type]
        processor,
        worker_count=1,
        max_retries=1,
    )

    recovered, reconciled = asyncio.run(worker.reconcile_startup())

    assert recovered == 2
    assert reconciled is True
    assert processor.seen == ["j1", "j2"]
    assert store.ready_updates[0][0] is False
    assert store.ready_updates[-1] == (True, None)


def test_startup_reconcile_keeps_not_ready_after_terminal_failure() -> None:
    store = _Store([{"user_id": "u1", "job_id": "j1", "attempts": 2}])
    processor = _Processor(store, fail=True)
    worker = PersonalKnowledgeBaseWorker(
        store,  # type: ignore[arg-type]
        processor,
        worker_count=1,
        max_retries=1,
    )

    _recovered, reconciled = asyncio.run(worker.reconcile_startup())

    assert reconciled is False
    assert store.ready_updates[-1][0] is False
    assert "explicit retry" in str(store.ready_updates[-1][1])


class _ConcurrentProcessor:
    job_types = ("upload", "delete")

    def __init__(self, store: _Store) -> None:
        self.store = store
        self.started: list[str] = []
        self.both_started = asyncio.Event()
        self.release = asyncio.Event()
        self.completed = 0

    async def process(self, job: dict) -> None:
        self.started.append(job["user_id"])
        if len(self.started) == 2:
            self.both_started.set()
        await self.release.wait()
        self.completed += 1
        if self.completed == 2:
            self.store.lag = False


def test_workers_process_different_users_concurrently() -> None:
    async def scenario() -> None:
        store = _Store(
            [
                {"user_id": "u1", "job_id": "j1", "attempts": 1},
                {"user_id": "u2", "job_id": "j2", "attempts": 1},
            ]
        )
        processor = _ConcurrentProcessor(store)
        worker = PersonalKnowledgeBaseWorker(
            store,  # type: ignore[arg-type]
            processor,
            worker_count=2,
            max_retries=1,
        )
        worker.start()
        await asyncio.wait_for(processor.both_started.wait(), timeout=1)
        assert set(processor.started) == {"u1", "u2"}
        processor.release.set()
        while processor.completed != 2:
            await asyncio.sleep(0)
        await worker.stop()

    asyncio.run(scenario())
