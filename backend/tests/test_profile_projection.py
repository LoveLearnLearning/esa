from types import SimpleNamespace

from backend.agent.memories.memory_models import ProfileOrigin
from backend.agent.memories.profile_projection import ProfileProjection


class StubUserStore:
    def get_by_username(self, username):
        return SimpleNamespace(id="u1", username=username) if username == "alice" else None


class StubProfileStore:
    def __init__(self):
        self.rows = {}
        self.deleted = []

    def get_dimension(self, user_id, field_key, *, include_expired=False):
        return self.rows.get((user_id, field_key))

    def upsert_dimension(
        self,
        user_id,
        field_key,
        value,
        origin,
        confidence,
        source_memory_ids=None,
        status="active",
        expires_at=None,
    ):
        self.rows[(user_id, field_key)] = {
            "user_id": user_id,
            "field_key": field_key,
            "value": value,
            "origin": origin,
            "confidence": confidence,
            "source_memory_ids": source_memory_ids or [],
            "status": status,
        }
        return True

    def delete_dimension(self, user_id, field_key, *, actor="system"):
        self.deleted.append((user_id, field_key, actor))
        return self.rows.pop((user_id, field_key), None) is not None


def _memory(**overrides):
    data = {
        "id": 7,
        "memory_key": "preferred_code_language",
        "content": "用户更喜欢 Python 示例",
        "category": "preference",
    }
    data.update(overrides)
    return data


def test_short_preference_projects_to_structured_profile():
    store = StubProfileStore()
    projection = ProfileProjection(StubUserStore(), store)

    result = projection.project_memory("alice", _memory())

    assert result.projected is True
    row = store.rows[("u1", "preferred_code_language")]
    assert row["value"] == "用户更喜欢 Python 示例"
    assert row["origin"] == ProfileOrigin.EXPLICIT_MEMORY.value
    assert row["source_memory_ids"] == ["7"]


def test_general_or_project_memory_is_not_auto_injected():
    store = StubProfileStore()
    projection = ProfileProjection(StubUserStore(), store)

    assert projection.project_memory("alice", _memory(category="general")).projected is False
    assert projection.project_memory("alice", _memory(category="project")).projected is False
    assert store.rows == {}


def test_reserved_explicit_setting_is_never_overwritten():
    store = StubProfileStore()
    projection = ProfileProjection(StubUserStore(), store)

    result = projection.project_memory(
        "alice",
        _memory(memory_key="preferred_style", content="detailed"),
    )

    assert result.projected is False
    assert result.reason == "reserved_explicit_setting_field"


def test_profile_category_requires_whitelisted_semantic_key():
    store = StubProfileStore()
    projection = ProfileProjection(StubUserStore(), store)

    private = projection.project_memory(
        "alice",
        _memory(memory_key="birthday", content="2000-01-01", category="profile"),
    )
    safe = projection.project_memory(
        "alice",
        _memory(memory_key="learning_preference", content="先例子后定义", category="profile"),
    )

    assert private.projected is False
    assert safe.projected is True


def test_suppressed_projection_is_not_silently_reactivated():
    store = StubProfileStore()
    store.rows[("u1", "preferred_code_language")] = {
        "origin": ProfileOrigin.EXPLICIT_MEMORY.value,
        "status": "suppressed",
        "source_memory_ids": ["7"],
    }
    projection = ProfileProjection(StubUserStore(), store)

    result = projection.project_memory("alice", _memory(content="现在更喜欢 Go"))

    assert result.projected is True
    assert store.rows[("u1", "preferred_code_language")]["status"] == "suppressed"


def test_delete_only_removes_projection_owned_by_same_memory():
    store = StubProfileStore()
    projection = ProfileProjection(StubUserStore(), store)
    projection.project_memory("alice", _memory())

    result = projection.remove_memory_projection("alice", _memory())

    assert result.reason == "projection_removed"
    assert ("u1", "preferred_code_language") not in store.rows
