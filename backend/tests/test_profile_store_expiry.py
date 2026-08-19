# backend/tests/test_profile_store_expiry.py

"""验证 `profile_store_expiry` 相关行为与回归场景。"""

import sqlite3
from datetime import datetime, timedelta

from backend.core.stores.profile_store import ProfileStore


def _db(tmp_path):
    """处理 `_db` 相关逻辑。"""
    path = tmp_path / "profile.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        )
        """
    )
    connection.execute(
        "INSERT INTO users(id, username, password_hash) VALUES('u1', 'alice', 'h')"
    )
    connection.commit()
    connection.close()
    return path


def test_runtime_reads_exclude_expired_dimensions_but_export_keeps_them(tmp_path):
    """验证 `runtime_reads_exclude_expired_dimensions_but_export_keeps_them` 场景。"""
    store = ProfileStore(_db(tmp_path))
    past = (datetime.now() - timedelta(minutes=1)).isoformat()
    future = (datetime.now() + timedelta(days=1)).isoformat()

    store.upsert_dimension(
        "u1", "expired", "old", "inferred_pattern", 0.7, expires_at=past
    )
    store.upsert_dimension(
        "u1", "future", "new", "inferred_pattern", 0.7, expires_at=future
    )

    assert store.get_dimension("u1", "expired") is None
    assert store.get_dimension("u1", "expired", include_expired=True) is not None

    runtime_keys = {row["field_key"] for row in store.list_dimensions("u1")}
    assert runtime_keys == {"future"}

    export_keys = {row["field_key"] for row in store.export_all_dimensions("u1")}
    assert export_keys == {"expired", "future"}
