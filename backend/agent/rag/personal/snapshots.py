"""Durable Qdrant snapshot creation for the personal collection."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import httpx

from backend.agent.rag.indexes import IndexUnavailable, PersonalQdrantIndex
from backend.core.stores.personal_knowledge_base_store import (
    PersonalKnowledgeBaseStore,
)


logger = logging.getLogger(__name__)


class PersonalQdrantSnapshotManager:
    """Coalesce mutations into checksummed snapshots on persistent storage."""

    def __init__(
        self,
        *,
        store: PersonalKnowledgeBaseStore,
        index: PersonalQdrantIndex,
        snapshot_root: str | Path,
        mutation_lock: asyncio.Lock,
        embedding_fingerprint: str,
        locator_schema_version: str,
        max_delay_seconds: int,
        retention: int,
        discard_file_artifacts: Callable[[str], None] | None = None,
    ) -> None:
        if max_delay_seconds <= 0:
            raise ValueError("snapshot max delay must be positive")
        if retention <= 0:
            raise ValueError("snapshot retention must be positive")
        self.store = store
        self.index = index
        self.snapshot_root = Path(snapshot_root).expanduser().resolve()
        self.mutation_lock = mutation_lock
        self.embedding_fingerprint = embedding_fingerprint
        self.locator_schema_version = locator_schema_version
        self.max_delay_seconds = max_delay_seconds
        self.retention = retention
        self.discard_file_artifacts = discard_file_artifacts
        self._wake = asyncio.Event()
        self._stopping = False
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None:
            return
        self.snapshot_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.snapshot_root, 0o700)
        self.store.ensure_collection_state(self.index.collection)
        self._stopping = False
        self._task = asyncio.create_task(
            self._run(), name="personal-kb-snapshot-manager"
        )
        self.notify()

    async def restore_or_initialize(
        self, *, dense_dimension: int, restore_enabled: bool
    ) -> tuple[str, int]:
        """Restore the exact high-water snapshot or request authority rebuild.

        The return mode is ``initialized``, ``restored``,
        ``replay_required``, or ``rebuild_required``. Readiness remains false
        until replay or rebuild has reconciled the SQLite high-water state.
        """

        self.snapshot_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.snapshot_root, 0o700)
        self.store.ensure_collection_state(self.index.collection)
        state = self.store.get_collection_state()
        if state is None:
            raise RuntimeError("personal collection state was not initialized")
        sequence = int(state["qdrant_mutation_seq"])
        if sequence == 0:
            await asyncio.to_thread(self.index.ensure_collection, dense_dimension)
            count = await asyncio.to_thread(self.index.maintenance_count_all)
            if count != 0:
                await asyncio.to_thread(
                    self.index.maintenance_recreate_collection, dense_dimension
                )
            await asyncio.to_thread(
                self.store.mark_collection_ready, ready=True, error=None
            )
            return "initialized", 0
        if not restore_enabled:
            message = (
                "personal Qdrant contains durable mutations but startup restore "
                "is disabled; authoritative rebuild is required"
            )
            self.store.mark_collection_ready(ready=False, error=message)
            return "rebuild_required", 0

        failures: list[str] = []
        for snapshot in self.store.list_valid_snapshots():
            snapshot_sequence = int(snapshot["qdrant_mutation_seq"])
            if snapshot_sequence > sequence:
                continue
            try:
                path = self._validate_snapshot_record(snapshot)
            except Exception as exc:
                self.store.invalidate_restorable_snapshot(
                    str(snapshot["snapshot_id"])
                )
                failures.append(
                    f"{snapshot['snapshot_id']}: {type(exc).__name__}"
                )
                logger.warning(
                    "invalid personal Qdrant snapshot id=%s",
                    snapshot["snapshot_id"],
                    exc_info=True,
                )
                continue
            try:
                await asyncio.to_thread(self._upload_snapshot, path)
                await asyncio.to_thread(
                    self.index.ensure_collection, dense_dimension
                )
                actual_count = await asyncio.to_thread(
                    self.index.maintenance_count_all
                )
                if actual_count != int(snapshot["point_count"]):
                    raise RuntimeError(
                        "restored Qdrant point count does not match snapshot"
                    )
                if snapshot_sequence == sequence:
                    await asyncio.to_thread(
                        self.store.mark_collection_ready, ready=True, error=None
                    )
                    return "restored", snapshot_sequence
                await asyncio.to_thread(
                    self.store.mark_collection_ready,
                    ready=False,
                    error=(
                        "personal snapshot restored below SQLite high-water; "
                        "ordered journal replay is required"
                    ),
                )
                return "replay_required", snapshot_sequence
            except Exception as exc:
                failures.append(f"{snapshot['snapshot_id']}: {type(exc).__name__}")
                logger.warning(
                    "personal Qdrant snapshot restore attempt failed id=%s",
                    snapshot["snapshot_id"],
                    exc_info=True,
                )
        message = (
            "no valid personal Qdrant snapshot covers SQLite mutation sequence "
            f"{sequence}; journal replay or full rebuild is required"
        )
        if failures:
            message += " (failed candidates: " + ", ".join(failures) + ")"
        self.store.mark_collection_ready(ready=False, error=message)
        return "rebuild_required", 0

    def notify(self) -> None:
        """Allow an operator or mutation path to request an early flush."""

        self._wake.set()

    async def stop(self) -> None:
        """Stop the timer and flush all committed mutations before shutdown."""

        self._stopping = True
        self._wake.set()
        task, self._task = self._task, None
        if task is not None:
            await task
        await self.create_if_dirty()

    async def _run(self) -> None:
        while not self._stopping:
            self._wake.clear()
            try:
                await asyncio.wait_for(
                    self._wake.wait(), timeout=self.max_delay_seconds
                )
            except TimeoutError:
                pass
            if self._stopping:
                break
            try:
                await self.create_if_dirty()
            except Exception:
                logger.exception("personal Qdrant periodic snapshot failed")

    async def create_if_dirty(self) -> bool:
        """Create one exact snapshot and atomically publish its durable copy."""

        snapshot_id = str(uuid.uuid4())
        final_path = self.snapshot_root / f"{snapshot_id}.snapshot"
        manifest_path = self.snapshot_root / f"{snapshot_id}.json"
        remote_name: str | None = None
        recorded = False
        try:
            # All Qdrant visible mutations and Qdrant snapshot creation share
            # this lock. The potentially slow NFS copy happens after release.
            async with self.mutation_lock:
                state = await asyncio.to_thread(self.store.get_collection_state)
                if state is None or not bool(state["snapshot_dirty"]):
                    return False
                sequence = int(state["qdrant_mutation_seq"])
                point_count = await asyncio.to_thread(
                    self.index.maintenance_count_all
                )
                response = await asyncio.to_thread(self._create_remote_snapshot)
                remote_name = self._snapshot_name(response)
                await asyncio.to_thread(
                    self.store.begin_snapshot,
                    snapshot_id=snapshot_id,
                    snapshot_path=str(final_path),
                    collection_name=self.index.collection,
                    point_count=point_count,
                    qdrant_mutation_seq=sequence,
                    embedding_fingerprint=self.embedding_fingerprint,
                    index_fingerprint=self.index.configuration_fingerprint,
                    locator_schema_version=self.locator_schema_version,
                )
                recorded = True

            digest = await asyncio.to_thread(
                self._download_snapshot, remote_name, final_path
            )
            await asyncio.to_thread(
                self._write_manifest,
                manifest_path,
                {
                    "schema_version": "personal-qdrant-snapshot-0.1",
                    "snapshot_id": snapshot_id,
                    "snapshot_path": str(final_path),
                    "sha256": digest,
                    "collection_name": self.index.collection,
                    "point_count": point_count,
                    "qdrant_mutation_seq": sequence,
                    "embedding_fingerprint": self.embedding_fingerprint,
                    "index_fingerprint": self.index.configuration_fingerprint,
                    "locator_schema_version": self.locator_schema_version,
                },
            )
            await asyncio.to_thread(
                self._verify_deletion_privacy, final_path, sequence
            )
            await asyncio.to_thread(
                self.store.commit_snapshot, snapshot_id=snapshot_id, sha256=digest
            )
            await asyncio.to_thread(self._purge_sensitive_snapshots, sequence)
            await asyncio.to_thread(self._apply_retention)
            return True
        except BaseException as exc:
            final_path.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
            if recorded:
                await asyncio.to_thread(
                    self.store.invalidate_snapshot,
                    snapshot_id=snapshot_id,
                    error=f"{type(exc).__name__}: {exc}",
                )
            raise
        finally:
            if remote_name is not None:
                try:
                    await asyncio.to_thread(self._delete_remote_snapshot, remote_name)
                except Exception:
                    logger.warning(
                        "failed to delete transient Qdrant snapshot %s",
                        remote_name,
                        exc_info=True,
                    )

    def _create_remote_snapshot(self) -> dict[str, Any]:
        return self.index._request(
            "POST",
            f"/collections/{quote(self.index.collection)}/snapshots?wait=true",
        )

    @staticmethod
    def _snapshot_name(response: dict[str, Any]) -> str:
        result = response.get("result")
        name = result if isinstance(result, str) else (
            result.get("name") if isinstance(result, dict) else None
        )
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            raise IndexUnavailable("Qdrant snapshot response has no safe name")
        return name

    def _download_snapshot(self, remote_name: str, final_path: Path) -> str:
        partial = final_path.with_name(f".{final_path.name}.partial")
        headers = {}
        if self.index.api_key:
            headers["api-key"] = self.index.api_key
        request = Request(
            f"{self.index.base_url.rstrip('/')}/collections/"
            f"{quote(self.index.collection)}/snapshots/{quote(remote_name)}",
            headers=headers,
            method="GET",
        )
        digest = hashlib.sha256()
        try:
            with urlopen(request, timeout=self.index.timeout) as response, partial.open(
                "xb"
            ) as stream:
                while block := response.read(1024 * 1024):
                    stream.write(block)
                    digest.update(block)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(partial, 0o600)
            os.replace(partial, final_path)
            directory_fd = os.open(final_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            partial.unlink(missing_ok=True)
            raise IndexUnavailable(f"Qdrant snapshot download failed: {exc}") from exc
        return digest.hexdigest()

    def _delete_remote_snapshot(self, remote_name: str) -> None:
        self.index._request(
            "DELETE",
            f"/collections/{quote(self.index.collection)}/snapshots/"
            f"{quote(remote_name)}?wait=true",
        )

    def _validate_snapshot_record(self, snapshot: dict[str, Any]) -> Path:
        if snapshot["collection_name"] != self.index.collection:
            raise RuntimeError("snapshot collection does not match configuration")
        if snapshot["embedding_fingerprint"] != self.embedding_fingerprint:
            raise RuntimeError("snapshot embedding fingerprint is incompatible")
        if snapshot["index_fingerprint"] != self.index.configuration_fingerprint:
            raise RuntimeError("snapshot index fingerprint is incompatible")
        if snapshot["locator_schema_version"] != self.locator_schema_version:
            raise RuntimeError("snapshot locator schema is incompatible")
        path = Path(snapshot["snapshot_path"]).resolve(strict=True)
        path.relative_to(self.snapshot_root)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
        if digest.hexdigest() != snapshot["sha256"]:
            raise RuntimeError("snapshot checksum verification failed")
        manifest_path = path.with_suffix(".json")
        manifest = json.loads(manifest_path.read_text("utf-8"))
        for key in (
            "snapshot_id", "sha256", "collection_name", "point_count",
            "qdrant_mutation_seq", "embedding_fingerprint",
            "index_fingerprint", "locator_schema_version",
        ):
            if manifest.get(key) != snapshot[key]:
                raise RuntimeError(f"snapshot manifest mismatch: {key}")
        return path

    def _upload_snapshot(
        self, path: Path, collection_name: str | None = None
    ) -> None:
        target_collection = collection_name or self.index.collection
        headers = {}
        if self.index.api_key:
            headers["api-key"] = self.index.api_key
        try:
            with path.open("rb") as stream, httpx.Client(
                timeout=self.index.timeout, trust_env=False
            ) as client:
                response = client.post(
                    f"{self.index.base_url.rstrip('/')}/collections/"
                    f"{quote(target_collection)}/snapshots/upload",
                    params={"priority": "snapshot", "wait": "true"},
                    headers=headers,
                    files={"snapshot": (path.name, stream, "application/octet-stream")},
                )
                response.raise_for_status()
        except (httpx.HTTPError, OSError) as exc:
            raise IndexUnavailable(f"Qdrant snapshot restore failed: {exc}") from exc

    def _verify_deletion_privacy(self, path: Path, covered_sequence: int) -> None:
        """Restore snapshot to a disposable collection and prove tombstones absent."""

        deletions = self.store.list_deletions_covered_by_snapshot(covered_sequence)
        user_purges = self.store.list_user_purges_covered_by_snapshot(
            covered_sequence
        )
        if not deletions and not user_purges:
            return
        verification_collection = (
            f"{self.index.collection}__privacy_verify_{uuid.uuid4().hex}"
        )
        verification_index = replace(
            self.index, collection=verification_collection
        )
        try:
            self._upload_snapshot(path, verification_collection)
            for deletion in deletions:
                if not verification_index.maintenance_file_absent(
                    user_id=str(deletion["user_id"]),
                    file_id=str(deletion["file_id"]),
                ):
                    raise RuntimeError(
                        "clean snapshot still contains a deleted personal file"
                    )
            for purge in user_purges:
                if not verification_index.maintenance_user_absent(
                    user_id=str(purge["user_id"])
                ):
                    raise RuntimeError(
                        "clean snapshot still contains a purged personal user"
                    )
        finally:
            verification_index.maintenance_delete_collection()

    @staticmethod
    def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
        partial = path.with_name(f".{path.name}.partial")
        try:
            with partial.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(partial, 0o600)
            os.replace(partial, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise

    def _apply_retention(self) -> None:
        snapshots = self.store.list_valid_snapshots()
        for snapshot in snapshots[self.retention :]:
            path = Path(snapshot["snapshot_path"])
            if path.parent.resolve() != self.snapshot_root:
                raise RuntimeError("snapshot retention path escaped configured root")
            path.unlink(missing_ok=True)
            path.with_suffix(".json").unlink(missing_ok=True)
            self.store.mark_snapshot_deleted(str(snapshot["snapshot_id"]))

    def _purge_sensitive_snapshots(self, covered_sequence: int) -> None:
        """Remove snapshots older than a deletion before sealing its cleanup."""

        deletions = self.store.list_deletions_covered_by_snapshot(covered_sequence)
        user_purges = self.store.list_user_purges_covered_by_snapshot(
            covered_sequence
        )
        if not deletions and not user_purges:
            return
        snapshots = self.store.list_valid_snapshots()
        privacy_events = [
            ("file", deletion, int(deletion["qdrant_mutation_seq"]))
            for deletion in deletions
        ] + [
            ("user", purge, int(purge["qdrant_mutation_seq"]))
            for purge in user_purges
        ]
        for event_type, event, deletion_sequence in privacy_events:
            for snapshot in snapshots:
                if int(snapshot["qdrant_mutation_seq"]) >= deletion_sequence:
                    continue
                path = Path(snapshot["snapshot_path"]).resolve()
                path.relative_to(self.snapshot_root)
                path.unlink(missing_ok=True)
                path.with_suffix(".json").unlink(missing_ok=True)
                self.store.mark_snapshot_deleted(str(snapshot["snapshot_id"]))
                snapshot["status"] = "deleted"
            if event_type == "file":
                if self.discard_file_artifacts is not None:
                    self.discard_file_artifacts(str(event["file_id"]))
                self.store.complete_deletion_cleanup(
                    user_id=str(event["user_id"]),
                    file_id=str(event["file_id"]),
                    qdrant_mutation_seq=deletion_sequence,
                )
            else:
                self.store.complete_user_purge(
                    purge_id=str(event["purge_id"]),
                    qdrant_mutation_seq=deletion_sequence,
                )
