# backend/tests/test_profile_store.py

"""验证 `profile_store` 相关行为与回归场景。"""

import sqlite3
from datetime import datetime, timedelta

from backend.core.stores.profile_store import ProfileStore


def _setup_db(tmp_path):
    """处理 `_setup_db` 相关逻辑。"""
    db_path = tmp_path / "test.db"
    # Create users table first (ProfileStore's FK references it)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        )
        """
    )
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES ('u1', 'alice', 'hash')"
    )
    conn.commit()
    conn.close()
    return db_path


def test_upsert_and_get_dimension(tmp_path):
    """验证 `upsert_and_get_dimension` 场景。"""
    db_path = _setup_db(tmp_path)
    store = ProfileStore(db_path)

    ok = store.upsert_dimension(
        user_id="u1",
        field_key="preferred_code_language",
        value="python",
        origin="inferred_pattern",
        confidence=0.7,
        source_memory_ids=["m1", "m2"],
    )
    assert ok is True

    dim = store.get_dimension("u1", "preferred_code_language")
    assert dim is not None
    assert dim["user_id"] == "u1"
    assert dim["field_key"] == "preferred_code_language"
    assert dim["value"] == "python"
    assert dim["origin"] == "inferred_pattern"
    assert dim["confidence"] == 0.7
    assert dim["status"] == "active"
    assert dim["source_memory_ids"] == ["m1", "m2"]
    assert dim["version"] == 1
    assert dim["created_at"] is not None
    assert dim["updated_at"] is not None


def test_upsert_updates_existing(tmp_path):
    """验证 `upsert_updates_existing` 场景。"""
    db_path = _setup_db(tmp_path)
    store = ProfileStore(db_path)

    store.upsert_dimension(
        user_id="u1",
        field_key="active_goal",
        value="learn-fastapi",
        origin="inferred_pattern",
        confidence=0.5,
    )
    store.upsert_dimension(
        user_id="u1",
        field_key="active_goal",
        value="learn-sqlalchemy",
        origin="inferred_pattern",
        confidence=0.9,
    )

    dim = store.get_dimension("u1", "active_goal")
    assert dim is not None
    assert dim["value"] == "learn-sqlalchemy"
    assert dim["confidence"] == 0.9
    assert dim["version"] == 2


def test_list_dimensions(tmp_path):
    """验证 `list_dimensions` 场景。"""
    db_path = _setup_db(tmp_path)
    store = ProfileStore(db_path)

    store.upsert_dimension("u1", "field_a", "a1", "inferred_pattern", 0.7)
    store.upsert_dimension("u1", "field_b", "b1", "inferred_pattern", 0.7)
    store.upsert_dimension(
        "u1", "field_c", "c1", "inferred_pattern", 0.7, status="suppressed"
    )

    all_dims = store.list_dimensions("u1")
    assert len(all_dims) == 3

    active = store.list_dimensions("u1", status_filter="active")
    assert len(active) == 2
    assert {d["field_key"] for d in active} == {"field_a", "field_b"}
    assert all(d["status"] == "active" for d in active)

    suppressed = store.list_dimensions("u1", status_filter="suppressed")
    assert len(suppressed) == 1
    assert suppressed[0]["field_key"] == "field_c"
    assert suppressed[0]["status"] == "suppressed"


def test_suppress_and_restore(tmp_path):
    """验证 `suppress_and_restore` 场景。"""
    db_path = _setup_db(tmp_path)
    store = ProfileStore(db_path)

    store.upsert_dimension(
        "u1", "preferred_style", "concise", "explicit_setting", 1.0
    )

    suppressed = store.suppress_dimension("u1", "preferred_style")
    assert suppressed is True
    dim = store.get_dimension("u1", "preferred_style")
    assert dim["status"] == "suppressed"
    assert dim["version"] == 2

    restored = store.restore_dimension("u1", "preferred_style")
    assert restored is True
    dim = store.get_dimension("u1", "preferred_style")
    assert dim["status"] == "active"
    assert dim["version"] == 3


def test_get_nonexistent(tmp_path):
    """验证 `get_nonexistent` 场景。"""
    db_path = _setup_db(tmp_path)
    store = ProfileStore(db_path)

    assert store.get_dimension("u1", "does_not_exist") is None


def test_suppress_nonexistent(tmp_path):
    """验证 `suppress_nonexistent` 场景。"""
    db_path = _setup_db(tmp_path)
    store = ProfileStore(db_path)

    assert store.suppress_dimension("u1", "ghost") is False


def test_cleanup_expired_dimensions(tmp_path):
    """验证 `cleanup_expired_dimensions` 场景。"""
    db_path = _setup_db(tmp_path)
    store = ProfileStore(db_path)
    now = datetime.now()

    # 1) expires_at 在过去 → 应被清理
    past_expires = (now - timedelta(days=1)).isoformat()
    store.upsert_dimension(
        "u1", "expired_field", "v", "inferred_pattern", 0.7,
        expires_at=past_expires,
    )

    # 2) expires_at 在未来 → 不应被清理
    future_expires = (now + timedelta(days=30)).isoformat()
    store.upsert_dimension(
        "u1", "future_field", "v", "inferred_pattern", 0.7,
        expires_at=future_expires,
    )

    # 3) suppressed 且 updated_at 很旧 → 应被清理
    store.upsert_dimension(
        "u1", "old_suppressed", "v", "inferred_pattern", 0.7,
        status="suppressed",
    )
    old_updated = (now - timedelta(days=100)).isoformat()
    store.execute(
        "UPDATE user_profile_dimensions SET updated_at = ? "
        "WHERE user_id = ? AND field_key = ?",
        (old_updated, "u1", "old_suppressed"),
    )

    # 4) suppressed 但 updated_at 很近 → 不应被清理
    store.upsert_dimension(
        "u1", "recent_suppressed", "v", "inferred_pattern", 0.7,
        status="suppressed",
    )

    # 执行清理 retention_days=90
    deleted = store.cleanup_expired_dimensions(retention_days=90)

    # 返回删除数 = expired_field + old_suppressed
    assert deleted == 2

    # 已过期记录被删除
    assert store.get_dimension("u1", "expired_field") is None
    # 旧 suppressed 记录被删除
    assert store.get_dimension("u1", "old_suppressed") is None
    # 未来过期记录保留
    assert store.get_dimension("u1", "future_field") is not None
    # 近期 suppressed 记录保留
    assert store.get_dimension("u1", "recent_suppressed") is not None
