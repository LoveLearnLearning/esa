import sqlite3

from backend.core.stores.profile_store import ProfileStore


def _setup_db(tmp_path):
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
    db_path = _setup_db(tmp_path)
    store = ProfileStore(db_path)

    assert store.get_dimension("u1", "does_not_exist") is None


def test_suppress_nonexistent(tmp_path):
    db_path = _setup_db(tmp_path)
    store = ProfileStore(db_path)

    assert store.suppress_dimension("u1", "ghost") is False
