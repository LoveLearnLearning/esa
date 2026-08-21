"""Tenant-wide privacy deletion for personal knowledge bases."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from backend.agent.rag.indexes import PersonalQdrantIndex
from backend.core.stores.personal_knowledge_base_store import (
    PersonalKnowledgeBaseStore,
)


class PersonalKnowledgeBaseUserPurger:
    """Delete every tenant point and artifact before releasing SQLite authority."""

    def __init__(
        self,
        *,
        store: PersonalKnowledgeBaseStore,
        index: PersonalQdrantIndex,
        mutation_lock: asyncio.Lock,
        discard_source: Callable[[str], None],
        discard_artifacts: Callable[[str], None],
        flush_snapshot: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self.store = store
        self.index = index
        self.mutation_lock = mutation_lock
        self.discard_source = discard_source
        self.discard_artifacts = discard_artifacts
        self.flush_snapshot = flush_snapshot

    async def purge(self, user_id: str) -> dict[str, Any]:
        """Run or resume a durable, idempotent purge for one trusted user."""

        record = await asyncio.to_thread(self.store.begin_user_purge, user_id)
        if record["status"] == "completed":
            return record
        purge_id = str(record["purge_id"])
        committed = record["status"] == "applied"
        try:
            if not committed:
                applying = await asyncio.to_thread(
                    self.store.mark_user_purge_applying,
                    purge_id=purge_id,
                    user_id=user_id,
                )
                if not applying:
                    raise RuntimeError("personal user purge is not apply eligible")
                # Snapshot creation and every visible Qdrant mutation use this
                # same lock. No snapshot can capture a half-deleted tenant.
                async with self.mutation_lock:
                    await asyncio.to_thread(
                        self.index.maintenance_delete_user, user_id=user_id
                    )
                    absent = await asyncio.to_thread(
                        self.index.maintenance_user_absent, user_id=user_id
                    )
                    if not absent:
                        raise RuntimeError(
                            "personal Qdrant tenant deletion verification failed"
                        )
                    for file_id in record["file_ids"]:
                        await asyncio.to_thread(self.discard_source, str(file_id))
                        await asyncio.to_thread(self.discard_artifacts, str(file_id))
                    await asyncio.to_thread(
                        self.store.commit_user_purge,
                        purge_id=purge_id,
                        user_id=user_id,
                    )
                committed = True
            if self.flush_snapshot is not None:
                await self.flush_snapshot()
            current = await asyncio.to_thread(self.store.get_user_purge, user_id)
            if current is None:
                raise RuntimeError("personal user purge audit record disappeared")
            return current
        except BaseException as exc:
            # Once SQLite records the mutation sequence, it must remain applied
            # even if snapshot flushing fails; dirty state makes that retryable.
            if not committed:
                await asyncio.to_thread(
                    self.store.fail_user_purge,
                    purge_id=purge_id,
                    user_id=user_id,
                    error=f"{type(exc).__name__}: {exc}",
                )
            raise
