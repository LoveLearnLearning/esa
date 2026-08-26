from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from backend.agent.rag.personal.snapshots import PersonalQdrantSnapshotManager


class _Store:
    def __init__(self) -> None:
        self.state = {
            "collection_name": "personal",
            "qdrant_mutation_seq": 7,
            "snapshot_mutation_seq": 0,
            "snapshot_dirty": 1,
        }
        self.snapshots: list[dict] = []

    def ensure_collection_state(self, collection_name: str) -> None:
        assert collection_name == "personal"

    def get_collection_state(self) -> dict:
        return dict(self.state)

    def begin_snapshot(self, **values) -> None:
        self.snapshots.append({**values, "status": "creating"})

    def commit_snapshot(self, *, snapshot_id: str, sha256: str) -> None:
        snapshot = next(
            value for value in self.snapshots if value["snapshot_id"] == snapshot_id
        )
        snapshot.update(status="valid", sha256=sha256)
        self.state["snapshot_mutation_seq"] = max(
            self.state["snapshot_mutation_seq"], snapshot["qdrant_mutation_seq"]
        )
        self.state["snapshot_dirty"] = int(
            self.state["qdrant_mutation_seq"] > snapshot["qdrant_mutation_seq"]
        )

    def invalidate_snapshot(self, *, snapshot_id: str, error: str) -> None:
        raise AssertionError((snapshot_id, error))

    def list_valid_snapshots(self) -> list[dict]:
        return [value for value in self.snapshots if value["status"] == "valid"]

    def mark_snapshot_deleted(self, snapshot_id: str) -> bool:
        for snapshot in self.snapshots:
            if snapshot["snapshot_id"] == snapshot_id:
                snapshot["status"] = "deleted"
                return True
        return False

    def invalidate_restorable_snapshot(self, snapshot_id: str) -> bool:
        for snapshot in self.snapshots:
            if snapshot["snapshot_id"] == snapshot_id:
                snapshot["status"] = "invalid"
                return True
        return False

    def list_deletions_covered_by_snapshot(self, sequence: int) -> list[dict]:
        return []

    def list_user_purges_covered_by_snapshot(self, sequence: int) -> list[dict]:
        return []

    def complete_deletion_cleanup(self, **values) -> bool:
        raise AssertionError(values)

    def complete_user_purge(self, **values) -> bool:
        raise AssertionError(values)

    def mark_collection_ready(self, *, ready: bool, error: str | None = None) -> None:
        self.state["ready"] = int(ready)
        self.state["error"] = error


class _Index:
    collection = "personal"
    base_url = "http://qdrant.invalid"
    api_key = None
    timeout = 1.0
    configuration_fingerprint = "index-fingerprint"

    def __init__(self) -> None:
        self.ensured_dimensions: list[int] = []

    def maintenance_count_all(self) -> int:
        return 11

    def maintenance_count_public(self, generation_id=None) -> int:
        return 0

    def maintenance_count_personal(self) -> int:
        return 0

    def maintenance_delete_personal_scope(self) -> None:
        pass

    def ensure_collection(self, dense_dimension: int) -> None:
        self.ensured_dimensions.append(dense_dimension)


class _SnapshotManager(PersonalQdrantSnapshotManager):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.deleted_remote: list[str] = []
        self.uploaded: list[Path] = []
        self.upload_targets: list[str | None] = []

    def _create_remote_snapshot(self) -> dict:
        return {"result": {"name": "remote.snapshot"}}

    def _download_snapshot(self, remote_name: str, final_path: Path) -> str:
        assert remote_name == "remote.snapshot"
        value = b"snapshot-bytes"
        final_path.write_bytes(value)
        # Simulate another committed mutation while the durable copy is slow.
        self.store.state["qdrant_mutation_seq"] = 8
        return hashlib.sha256(value).hexdigest()

    def _delete_remote_snapshot(self, remote_name: str) -> None:
        self.deleted_remote.append(remote_name)

    def _upload_snapshot(
        self, path: Path, collection_name: str | None = None
    ) -> None:
        self.uploaded.append(path)
        self.upload_targets.append(collection_name)


def test_snapshot_keeps_dirty_when_mutation_arrives_during_copy(tmp_path: Path) -> None:
    store = _Store()
    manager = _SnapshotManager(
        store=store,
        index=_Index(),
        snapshot_root=tmp_path,
        mutation_lock=asyncio.Lock(),
        embedding_fingerprint="embedding-fingerprint",
        locator_schema_version="personal-locator-0.1",
        max_delay_seconds=600,
        retention=3,
    )

    created = asyncio.run(manager.create_if_dirty())

    assert created is True
    assert store.state["snapshot_mutation_seq"] == 7
    assert store.state["snapshot_dirty"] == 1
    assert store.snapshots[0]["point_count"] == 11
    assert Path(store.snapshots[0]["snapshot_path"]).is_file()
    assert Path(store.snapshots[0]["snapshot_path"]).with_suffix(".json").is_file()
    assert manager.deleted_remote == ["remote.snapshot"]


def test_snapshot_is_skipped_when_collection_is_clean(tmp_path: Path) -> None:
    store = _Store()
    store.state["snapshot_dirty"] = 0
    manager = _SnapshotManager(
        store=store,
        index=_Index(),
        snapshot_root=tmp_path,
        mutation_lock=asyncio.Lock(),
        embedding_fingerprint="embedding-fingerprint",
        locator_schema_version="personal-locator-0.1",
        max_delay_seconds=600,
        retention=3,
    )

    assert asyncio.run(manager.create_if_dirty()) is False
    assert store.snapshots == []


class _InterruptedStore(_Store):
    def invalidate_snapshot(self, *, snapshot_id: str, error: str) -> None:
        snapshot = next(
            value for value in self.snapshots if value["snapshot_id"] == snapshot_id
        )
        snapshot.update(status="invalid", error=error)
        self.state["snapshot_dirty"] = 1


class _InterruptedSnapshotManager(_SnapshotManager):
    def _download_snapshot(self, remote_name: str, final_path: Path) -> str:
        final_path.write_bytes(b"incomplete")
        raise OSError("simulated snapshot copy interruption")


def test_snapshot_copy_interruption_keeps_committed_sqlite_dirty_and_retryable(
    tmp_path: Path,
) -> None:
    store = _InterruptedStore()
    manager = _InterruptedSnapshotManager(
        store=store,
        index=_Index(),
        snapshot_root=tmp_path,
        mutation_lock=asyncio.Lock(),
        embedding_fingerprint="embedding-fingerprint",
        locator_schema_version="personal-locator-0.1",
        max_delay_seconds=600,
        retention=3,
    )

    try:
        asyncio.run(manager.create_if_dirty())
    except OSError as exc:
        assert "simulated" in str(exc)
    else:
        raise AssertionError("snapshot interruption was not propagated")

    assert store.state["qdrant_mutation_seq"] == 7
    assert store.state["snapshot_mutation_seq"] == 0
    assert store.state["snapshot_dirty"] == 1
    assert store.snapshots[0]["status"] == "invalid"
    assert list(tmp_path.iterdir()) == []
    assert manager.deleted_remote == ["remote.snapshot"]


def test_snapshot_manifest_is_private_and_durable(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"

    PersonalQdrantSnapshotManager._write_manifest(path, {"ok": True})

    if os.name == "posix":
        assert path.stat().st_uid == os.geteuid()
        assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text("utf-8")) == {"ok": True}


def test_snapshot_retention_deletes_only_records_beyond_newest_limit(
    tmp_path: Path,
) -> None:
    store = _Store()
    for sequence in (3, 2, 1):
        path = tmp_path / f"s{sequence}.snapshot"
        path.write_bytes(b"snapshot")
        path.with_suffix(".json").write_text("{}", encoding="utf-8")
        store.snapshots.append(
            {
                "snapshot_id": f"s{sequence}",
                "snapshot_path": str(path),
                "qdrant_mutation_seq": sequence,
                "status": "valid",
            }
        )
    manager = _SnapshotManager(
        store=store,
        index=_Index(),
        snapshot_root=tmp_path,
        mutation_lock=asyncio.Lock(),
        embedding_fingerprint="embedding-fingerprint",
        locator_schema_version="personal-locator-0.1",
        max_delay_seconds=600,
        retention=2,
    )

    manager._apply_retention()

    assert [value["status"] for value in store.snapshots] == [
        "valid", "valid", "deleted"
    ]
    assert not (tmp_path / "s1.snapshot").exists()
    assert (tmp_path / "s2.snapshot").exists()


def test_restore_requires_snapshot_at_exact_sqlite_sequence(tmp_path: Path) -> None:
    store = _Store()
    store.snapshots.append(
        {
            "snapshot_id": "old",
            "snapshot_path": str(tmp_path / "old.snapshot"),
            "sha256": "a" * 64,
            "collection_name": "personal",
            "point_count": 11,
            "qdrant_mutation_seq": 6,
            "embedding_fingerprint": "embedding-fingerprint",
            "index_fingerprint": "index-fingerprint",
            "locator_schema_version": "personal-locator-0.1",
            "status": "valid",
        }
    )
    manager = _SnapshotManager(
        store=store,
        index=_Index(),
        snapshot_root=tmp_path,
        mutation_lock=asyncio.Lock(),
        embedding_fingerprint="embedding-fingerprint",
        locator_schema_version="personal-locator-0.1",
        max_delay_seconds=600,
        retention=3,
    )

    result = asyncio.run(
        manager.restore_or_initialize(
            dense_dimension=2560, restore_enabled=True
        )
    )

    assert result == ("rebuild_required", 0)
    assert store.state["ready"] == 0


def test_restore_accepts_only_exact_checksummed_compatible_snapshot(
    tmp_path: Path,
) -> None:
    store = _Store()
    snapshot_path = tmp_path / "exact.snapshot"
    snapshot_path.write_bytes(b"exact-snapshot")
    digest = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    record = {
        "snapshot_id": "exact",
        "snapshot_path": str(snapshot_path),
        "sha256": digest,
        "collection_name": "personal",
        "point_count": 11,
        "qdrant_mutation_seq": 7,
        "embedding_fingerprint": "embedding-fingerprint",
        "index_fingerprint": "index-fingerprint",
        "locator_schema_version": "personal-locator-0.1",
        "status": "valid",
    }
    store.snapshots.append(record)
    snapshot_path.with_suffix(".json").write_text(
        json.dumps({
            "schema_version": "unified-qdrant-snapshot-0.2",
            "public_generation_id": None,
            "public_chunk_count": 0,
            **record,
        }),
        encoding="utf-8",
    )
    manager = _SnapshotManager(
        store=store,
        index=_Index(),
        snapshot_root=tmp_path,
        mutation_lock=asyncio.Lock(),
        embedding_fingerprint="embedding-fingerprint",
        locator_schema_version="personal-locator-0.1",
        max_delay_seconds=600,
        retention=3,
    )

    result = asyncio.run(
        manager.restore_or_initialize(
            dense_dimension=2560, restore_enabled=True
        )
    )

    assert result == ("restored", 7)
    assert manager.uploaded == [snapshot_path]
    assert store.state["ready"] == 1


def test_snapshot_rejects_another_public_generation(tmp_path: Path) -> None:
    store = _Store()
    snapshot_path = tmp_path / "wrong-public.snapshot"
    snapshot_path.write_bytes(b"wrong-public")
    record = {
        "snapshot_id": "wrong-public",
        "snapshot_path": str(snapshot_path),
        "sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
        "collection_name": "personal",
        "point_count": 11,
        "qdrant_mutation_seq": 7,
        "embedding_fingerprint": "embedding-fingerprint",
        "index_fingerprint": "index-fingerprint",
        "locator_schema_version": "personal-locator-0.1",
        "status": "valid",
    }
    store.snapshots.append(record)
    snapshot_path.with_suffix(".json").write_text(
        json.dumps(
            {
                "schema_version": "unified-qdrant-snapshot-0.2",
                "public_generation_id": "public-old",
                "public_chunk_count": 9,
                **record,
            }
        ),
        encoding="utf-8",
    )
    manager = _SnapshotManager(
        store=store,
        index=_Index(),
        snapshot_root=tmp_path,
        mutation_lock=asyncio.Lock(),
        embedding_fingerprint="embedding-fingerprint",
        locator_schema_version="personal-locator-0.1",
        max_delay_seconds=600,
        retention=3,
        public_generation_id="public-live",
        public_chunk_count=11,
    )

    with pytest.raises(RuntimeError, match="public generation"):
        manager._validate_snapshot_record(record)


def test_restore_accepts_older_snapshot_but_keeps_readiness_false_for_replay(
    tmp_path: Path,
) -> None:
    store = _Store()
    snapshot_path = tmp_path / "older.snapshot"
    snapshot_path.write_bytes(b"older-snapshot")
    digest = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    record = {
        "snapshot_id": "older",
        "snapshot_path": str(snapshot_path),
        "sha256": digest,
        "collection_name": "personal",
        "point_count": 11,
        "qdrant_mutation_seq": 6,
        "embedding_fingerprint": "embedding-fingerprint",
        "index_fingerprint": "index-fingerprint",
        "locator_schema_version": "personal-locator-0.1",
        "status": "valid",
    }
    store.snapshots.append(record)
    snapshot_path.with_suffix(".json").write_text(
        json.dumps({
            "schema_version": "unified-qdrant-snapshot-0.2",
            "public_generation_id": None,
            "public_chunk_count": 0,
            **record,
        }),
        encoding="utf-8",
    )
    manager = _SnapshotManager(
        store=store,
        index=_Index(),
        snapshot_root=tmp_path,
        mutation_lock=asyncio.Lock(),
        embedding_fingerprint="embedding-fingerprint",
        locator_schema_version="personal-locator-0.1",
        max_delay_seconds=600,
        retention=3,
    )

    result = asyncio.run(
        manager.restore_or_initialize(
            dense_dimension=2560, restore_enabled=True
        )
    )

    assert result == ("replay_required", 6)
    assert manager.uploaded == [snapshot_path]
    assert store.state["qdrant_mutation_seq"] == 7
    assert store.state["ready"] == 0


def test_restore_invalidates_corrupt_latest_snapshot_and_falls_back(
    tmp_path: Path,
) -> None:
    store = _Store()
    for snapshot_id, sequence, contents in (
        ("latest", 7, b"corrupt-latest"),
        ("older", 6, b"valid-older"),
    ):
        path = tmp_path / f"{snapshot_id}.snapshot"
        path.write_bytes(contents)
        digest = hashlib.sha256(contents).hexdigest()
        record = {
            "snapshot_id": snapshot_id,
            "snapshot_path": str(path),
            "sha256": ("0" * 64 if snapshot_id == "latest" else digest),
            "collection_name": "personal",
            "point_count": 11,
            "qdrant_mutation_seq": sequence,
            "embedding_fingerprint": "embedding-fingerprint",
            "index_fingerprint": "index-fingerprint",
            "locator_schema_version": "personal-locator-0.1",
            "status": "valid",
        }
        store.snapshots.append(record)
        path.with_suffix(".json").write_text(
            json.dumps({
                "schema_version": "unified-qdrant-snapshot-0.2",
                "public_generation_id": None,
                "public_chunk_count": 0,
                **record,
            }),
            encoding="utf-8",
        )
    manager = _SnapshotManager(
        store=store,
        index=_Index(),
        snapshot_root=tmp_path,
        mutation_lock=asyncio.Lock(),
        embedding_fingerprint="embedding-fingerprint",
        locator_schema_version="personal-locator-0.1",
        max_delay_seconds=600,
        retention=3,
    )

    result = asyncio.run(
        manager.restore_or_initialize(dense_dimension=2560, restore_enabled=True)
    )

    assert result == ("replay_required", 6)
    assert store.snapshots[0]["status"] == "invalid"
    assert manager.uploaded == [tmp_path / "older.snapshot"]


class _PrivacyStore(_Store):
    def __init__(self) -> None:
        super().__init__()
        self.completed: list[dict] = []

    def list_deletions_covered_by_snapshot(self, sequence: int) -> list[dict]:
        assert sequence == 7
        return [
            {"user_id": "u1", "file_id": "deleted", "qdrant_mutation_seq": 7}
        ]

    def complete_deletion_cleanup(self, **values) -> bool:
        self.completed.append(values)
        return True


class _UserPrivacyStore(_Store):
    def __init__(self) -> None:
        super().__init__()
        self.completed_user_purges: list[dict] = []

    def list_user_purges_covered_by_snapshot(self, sequence: int) -> list[dict]:
        assert sequence == 7
        return [
            {"purge_id": "purge-1", "user_id": "u1", "qdrant_mutation_seq": 7}
        ]

    def complete_user_purge(self, **values) -> bool:
        self.completed_user_purges.append(values)
        return True


@dataclass(frozen=True)
class _PrivacyIndex:
    collection: str = "personal"
    base_url: str = "http://qdrant.invalid"
    api_key: str | None = None
    timeout: float = 1.0
    configuration_fingerprint: str = "index-fingerprint"
    checks: list[tuple[str, str, str]] = field(default_factory=list)
    user_checks: list[tuple[str, str]] = field(default_factory=list)
    deleted_collections: list[str] = field(default_factory=list)

    def maintenance_count_all(self) -> int:
        return 0

    def maintenance_count_public(self, generation_id=None) -> int:
        return 0

    def maintenance_file_absent(self, *, user_id: str, file_id: str) -> bool:
        self.checks.append((self.collection, user_id, file_id))
        return True

    def maintenance_user_absent(self, *, user_id: str) -> bool:
        self.user_checks.append((self.collection, user_id))
        return True

    def maintenance_delete_collection(self) -> None:
        self.deleted_collections.append(self.collection)


def test_clean_snapshot_is_restored_to_temporary_collection_before_cleanup(
    tmp_path: Path,
) -> None:
    store = _PrivacyStore()
    index = _PrivacyIndex()
    discarded_artifacts: list[str] = []
    manager = _SnapshotManager(
        store=store,
        index=index,  # type: ignore[arg-type]
        snapshot_root=tmp_path,
        mutation_lock=asyncio.Lock(),
        embedding_fingerprint="embedding-fingerprint",
        locator_schema_version="personal-locator-0.1",
        max_delay_seconds=600,
        retention=3,
        discard_file_artifacts=discarded_artifacts.append,
    )

    assert asyncio.run(manager.create_if_dirty()) is True

    verification_collection = manager.upload_targets[-1]
    assert verification_collection is not None
    assert verification_collection.startswith("personal__privacy_verify_")
    assert index.checks == [
        (verification_collection, "u1", "deleted")
    ]
    assert index.deleted_collections == [verification_collection]
    assert discarded_artifacts == ["deleted"]
    assert store.completed == [
        {"user_id": "u1", "file_id": "deleted", "qdrant_mutation_seq": 7}
    ]


def test_privacy_cleanup_removes_every_snapshot_older_than_deletion(
    tmp_path: Path,
) -> None:
    store = _PrivacyStore()
    for snapshot_id, sequence in (("new", 7), ("old", 6), ("older", 2)):
        path = tmp_path / f"{snapshot_id}.snapshot"
        path.write_bytes(b"snapshot")
        path.with_suffix(".json").write_text("{}", encoding="utf-8")
        store.snapshots.append(
            {
                "snapshot_id": snapshot_id,
                "snapshot_path": str(path),
                "qdrant_mutation_seq": sequence,
                "status": "valid",
            }
        )
    discarded: list[str] = []
    manager = _SnapshotManager(
        store=store,
        index=_PrivacyIndex(),  # type: ignore[arg-type]
        snapshot_root=tmp_path,
        mutation_lock=asyncio.Lock(),
        embedding_fingerprint="embedding-fingerprint",
        locator_schema_version="personal-locator-0.1",
        max_delay_seconds=600,
        retention=3,
        discard_file_artifacts=discarded.append,
    )

    manager._purge_sensitive_snapshots(7)

    assert [value["status"] for value in store.snapshots] == [
        "valid", "deleted", "deleted"
    ]
    assert (tmp_path / "new.snapshot").exists()
    assert not (tmp_path / "old.snapshot").exists()
    assert not (tmp_path / "older.snapshot").exists()
    assert discarded == ["deleted"]
    assert len(store.completed) == 1


def test_clean_snapshot_verifies_user_purge_and_destroys_older_snapshots(
    tmp_path: Path,
) -> None:
    store = _UserPrivacyStore()
    old_path = tmp_path / "old.snapshot"
    old_path.write_bytes(b"old")
    old_path.with_suffix(".json").write_text("{}", encoding="utf-8")
    store.snapshots.append(
        {
            "snapshot_id": "old",
            "snapshot_path": str(old_path),
            "qdrant_mutation_seq": 6,
            "status": "valid",
        }
    )
    index = _PrivacyIndex()
    manager = _SnapshotManager(
        store=store,
        index=index,  # type: ignore[arg-type]
        snapshot_root=tmp_path,
        mutation_lock=asyncio.Lock(),
        embedding_fingerprint="embedding-fingerprint",
        locator_schema_version="personal-locator-0.1",
        max_delay_seconds=600,
        retention=3,
    )

    assert asyncio.run(manager.create_if_dirty()) is True

    verification_collection = manager.upload_targets[-1]
    assert index.user_checks == [(verification_collection, "u1")]
    assert not old_path.exists()
    assert store.completed_user_purges == [
        {"purge_id": "purge-1", "qdrant_mutation_seq": 7}
    ]
