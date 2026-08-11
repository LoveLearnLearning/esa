from backend.agent.memories.memory_models import ProfileQuery
from backend.agent.memories.profile_builder import ProfileBuilder
from backend.core.utils.models import MemorySettings, UserRecord


class UserStore:
    def __init__(self, user):
        self.user = user

    def get_by_id(self, user_id):
        return self.user

    def get_memory_settings(self, user_id):
        return MemorySettings(user_id=user_id)


class MasteryStore:
    DEFAULT_MASTERY = 50.0

    def get(self, user_name, kp_id):
        return None

    def get_weak_prerequisites(self, user_name, kp_id, kg_store):
        return []


class KGStore:
    def list_all(self):
        return []


class EvidenceStore:
    def get_summary(self, user_name, *, kp_id=None, limit=20):
        raise AssertionError("No resolved knowledge point should request evidence")


class ProfileStore:
    def __init__(self):
        self.rows = []
        self.version = 0

    def list_dimensions(self, user_id, status_filter=None):
        rows = self.rows
        if status_filter is not None:
            rows = [row for row in rows if row.get("status") == status_filter]
        return rows

    def get_next_profile_version(self, user_id):
        self.version += 1
        return self.version


def make_user():
    return UserRecord(
        id="u1",
        username="alice",
        password_hash="h",
        status="active",
        preferred_style="concise",
        preferred_tone="friendly",
        custom_instruction="",
        major="cs",
        grade="大二",
        current_week=3,
        total_weeks=18,
    )


def make_builder(user=None):
    user = user or make_user()
    profile_store = ProfileStore()
    return (
        ProfileBuilder(
            UserStore(user),
            MasteryStore(),
            KGStore(),
            profile_store,
            EvidenceStore(),
        ),
        profile_store,
        user,
    )


def test_cache_key_changes_for_group_tone_and_recent_messages():
    builder, _, user = make_builder()
    settings = MemorySettings(user_id="u1")

    q1 = ProfileQuery(user_id="u1", username="alice", group_tone="formal")
    q2 = ProfileQuery(user_id="u1", username="alice", group_tone="friendly")
    assert builder._compute_hash(user, q1, settings) != builder._compute_hash(user, q2, settings)

    q3 = ProfileQuery(
        user_id="u1",
        username="alice",
        recent_messages=[{"role": "user", "content": "二叉树"}],
    )
    q4 = ProfileQuery(
        user_id="u1",
        username="alice",
        recent_messages=[{"role": "user", "content": "操作系统"}],
    )
    assert builder._compute_hash(user, q3, settings) != builder._compute_hash(user, q4, settings)

    q5 = ProfileQuery(user_id="u1", username="alice", resolved_kp_ids=["二叉树"])
    q6 = ProfileQuery(user_id="u1", username="alice", resolved_kp_ids=["递归"])
    assert builder._compute_hash(user, q5, settings) != builder._compute_hash(user, q6, settings)


def test_cache_key_changes_when_user_profile_inputs_change():
    builder, _, user = make_builder()
    settings = MemorySettings(user_id="u1")
    query = ProfileQuery(user_id="u1", username="alice")

    before = builder._compute_hash(user, query, settings)
    user.preferred_tone = "strict"
    after_tone = builder._compute_hash(user, query, settings)
    assert after_tone != before

    user.total_weeks = 20
    after_weeks = builder._compute_hash(user, query, settings)
    assert after_weeks != after_tone


def test_cache_key_changes_when_profile_store_revision_changes():
    builder, store, user = make_builder()
    settings = MemorySettings(user_id="u1")
    query = ProfileQuery(user_id="u1", username="alice")

    before = builder._compute_hash(user, query, settings)
    store.rows = [
        {
            "field_key": "preferred_code_language",
            "origin": "explicit_memory",
            "status": "active",
            "version": 1,
            "updated_at": "2026-08-07T12:00:00",
            "expires_at": None,
        }
    ]
    after = builder._compute_hash(user, query, settings)
    assert after != before
