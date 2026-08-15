# backend/tests/test_profile_cache_key.py

"""验证 `profile_cache_key` 相关行为与回归场景。"""

from backend.agent.memories.memory_models import ProfileQuery
from backend.agent.memories.profile_builder import ProfileBuilder
from backend.core.utils.models import MemorySettings, UserRecord


class UserStore:
    """封装 `user store` 数据持久化操作。"""
    def __init__(self, user):
        """初始化 `UserStore` 实例。"""
        self.user = user

    def get_by_id(self, user_id):
        """获取 `by id` 相关数据。"""
        return self.user

    def get_memory_settings(self, user_id):
        """获取 `memory settings` 相关数据。"""
        return MemorySettings(user_id=user_id)


class MasteryStore:
    """封装 `mastery store` 数据持久化操作。"""
    DEFAULT_MASTERY = 50.0

    def get(self, user_name, kp_id):
        """获取 `get` 相关数据。

        Args:
            user_name: object => `user_name` 参数。
            kp_id: object => kp ID。

        Returns:
            object => 处理结果。
        """
        return None

    def get_weak_prerequisites(self, user_name, kp_id, kg_store):
        """获取 `weak prerequisites` 相关数据。

        Args:
            user_name: object => `user_name` 参数。
            kp_id: object => kp ID。
            kg_store: object => `kg_store` 参数。

        Returns:
            object => 处理结果。
        """
        return []


class KGStore:
    """封装 `k g store` 数据持久化操作。"""
    def list_all(self):
        """列出 `all` 相关数据。"""
        return []


class EvidenceStore:
    """封装 `evidence store` 数据持久化操作。"""
    def get_summary(self, user_name, *, kp_id=None, limit=20):
        """获取 `summary` 相关数据。

        Args:
            user_name: object => `user_name` 参数。
            kp_id: object => kp ID。
            limit: object => 返回数量上限。
        """
        raise AssertionError("No resolved knowledge point should request evidence")


class ProfileStore:
    """封装 `profile store` 数据持久化操作。"""
    def __init__(self):
        """初始化 `ProfileStore` 实例。"""
        self.rows = []
        self.version = 0

    def list_dimensions(self, user_id, status_filter=None):
        """列出 `dimensions` 相关数据。

        Args:
            user_id: object => 用户 ID。
            status_filter: object => `status_filter` 参数。

        Returns:
            object => 处理结果。
        """
        rows = self.rows
        if status_filter is not None:
            rows = [row for row in rows if row.get("status") == status_filter]
        return rows

    def get_next_profile_version(self, user_id):
        """获取 `next profile version` 相关数据。"""
        self.version += 1
        return self.version


def make_user():
    """处理 `make_user` 相关逻辑。"""
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
    """处理 `make_builder` 相关逻辑。

    Args:
        user: object => `user` 参数。

    Returns:
        object => 处理结果。
    """
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
    """验证 `cache_key_changes_for_group_tone_and_recent_messages` 场景。"""
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
    """验证 `cache_key_changes_when_user_profile_inputs_change` 场景。"""
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
    """验证 `cache_key_changes_when_profile_store_revision_changes` 场景。"""
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
