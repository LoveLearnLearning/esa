# backend/tests/test_profile_builder.py

"""验证 `profile_builder` 相关行为与回归场景。"""

from backend.agent.memories.memory_models import ProfileOrigin, ProfileQuery
from backend.agent.memories.profile_builder import ProfileBuilder
from backend.core.utils.models import MemorySettings, UserRecord


class StubUserStore:
    """封装 `stub user store` 数据持久化操作。"""
    def __init__(self, user, settings=None):
        """初始化 `StubUserStore` 实例。"""
        self._user = user
        self._settings = settings

    def get_by_id(self, user_id):
        """获取 `by id` 相关数据。"""
        return self._user

    def get_memory_settings(self, user_id):
        """获取 `memory settings` 相关数据。"""
        return self._settings


class StubMasteryStore:
    """封装 `stub mastery store` 数据持久化操作。"""
    DEFAULT_MASTERY = 50.0

    def __init__(self, mastery_map=None, prereqs=None):
        """初始化 `StubMasteryStore` 实例。"""
        self._mastery_map = mastery_map or {}  # kp_id -> dict
        self._prereqs = prereqs or []

    def get(self, user_name, kp_id):
        """获取 `get` 相关数据。

        Args:
            user_name: object => `user_name` 参数。
            kp_id: object => kp ID。

        Returns:
            object => 处理结果。
        """
        return self._mastery_map.get(kp_id)

    def get_weak_prerequisites(
        self, user_name, kp_id, kg_store, mastery_threshold=50.0, max_depth=5
    ):
        """获取 `weak prerequisites` 相关数据。

        Args:
            user_name: object => `user_name` 参数。
            kp_id: object => kp ID。
            kg_store: object => `kg_store` 参数。
            mastery_threshold: object => `mastery_threshold` 参数。
            max_depth: object => `max_depth` 参数。

        Returns:
            object => 处理结果。
        """
        return self._prereqs


class StubKGStore:
    """封装 `stub k g store` 数据持久化操作。"""
    def __init__(self, points=None, prerequisites=None):
        """初始化 `StubKGStore` 实例。"""
        self._points = points or []
        self._prerequisites = prerequisites or {}

    def list_all(self):
        """列出 `all` 相关数据。"""
        return self._points

    def get_point(self, kp_id):
        """获取 `point` 相关数据。"""
        return next((point for point in self._points if point["id"] == kp_id), None)

    def get_prerequisites(self, kp_id, max_depth=3):
        """获取 `prerequisites` 相关数据。

        Args:
            kp_id: object => kp ID。
            max_depth: object => `max_depth` 参数。

        Returns:
            object => 处理结果。
        """
        point = self.get_point(kp_id)
        if point is None:
            return []
        return [
            {
                "kp_id": kp_id,
                "name": point["name"],
                "course": point.get("course", "course"),
                "depth": 0,
                "weight": point.get("weight", 0.0),
            },
            *self._prerequisites.get(kp_id, []),
        ]


class StubEvidenceStore:
    """封装 `stub evidence store` 数据持久化操作。"""
    def get_summary(self, user_name, *, kp_id=None, limit=20):
        """获取 `summary` 相关数据。

        Args:
            user_name: object => `user_name` 参数。
            kp_id: object => kp ID。
            limit: object => 返回数量上限。

        Returns:
            object => 处理结果。
        """
        return {
            "evidence_count": 0,
            "correct_rate": None,
            "avg_hint_level": None,
            "independent_rate": None,
            "avg_explanation_score": None,
            "avg_transfer_score": None,
            "recent_misconceptions": [],
        }


class StubCoreMemory:
    """封装 `StubCoreMemory` 的状态与行为。"""
    def __init__(self, memories=None):
        """初始化 `StubCoreMemory` 实例。"""
        self._memories = memories or []

    def get_all(self, user_name):
        """获取 `all` 相关数据。"""
        return self._memories


class StubProfileStore:
    """封装 `stub profile store` 数据持久化操作。"""
    def __init__(self, suppressed=None):
        """初始化 `StubProfileStore` 实例。"""
        self._suppressed = suppressed or []  # list of dicts with field_key
        self.upserts = []

    def list_dimensions(self, user_id, status_filter=None):
        """列出 `dimensions` 相关数据。

        Args:
            user_id: object => 用户 ID。
            status_filter: object => `status_filter` 参数。

        Returns:
            object => 处理结果。
        """
        if status_filter == "suppressed":
            return self._suppressed
        return []

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
        """处理 `upsert_dimension` 相关逻辑。

        Args:
            user_id: object => 用户 ID。
            field_key: object => `field_key` 参数。
            value: object => 输入值。
            origin: object => `origin` 参数。
            confidence: object => `confidence` 参数。
            source_memory_ids: object => `source_memory_ids` 参数。
            status: object => `status` 参数。
            expires_at: object => `expires_at` 参数。

        Returns:
            object => 处理结果。
        """
        self.upserts.append({"field_key": field_key, "value": value})
        return True

    def get_dimension(self, user_id, field_key):
        """获取 `dimension` 相关数据。

        Args:
            user_id: object => 用户 ID。
            field_key: object => `field_key` 参数。

        Returns:
            object => 处理结果。
        """
        return None

    def suppress_dimension(self, user_id, field_key):
        """处理 `suppress_dimension` 相关逻辑。

        Args:
            user_id: object => 用户 ID。
            field_key: object => `field_key` 参数。

        Returns:
            object => 处理结果。
        """
        return True


def _make_user():
    """处理 `_make_user` 相关逻辑。"""
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
        profile_enabled=True,
        learning_profile_enabled=True,
        inferred_profile_enabled=True,
    )


def _make_settings(learning=True, inferred=True):
    """处理 `_make_settings` 相关逻辑。"""
    return MemorySettings(
        user_id="u1",
        learning_profile_enabled=learning,
        inferred_profile_enabled=inferred,
    )


def _make_builder(
    user=None,
    settings=None,
    mastery_map=None,
    prereqs=None,
    kg_points=None,
    memories=None,
    suppressed=None,
):
    """处理 `_make_builder` 相关逻辑。"""
    user = user or _make_user()
    user_store = StubUserStore(user, settings)
    mastery_store = StubMasteryStore(mastery_map, prereqs)
    kg_store = StubKGStore(kg_points)
    profile_store = StubProfileStore(suppressed)
    return ProfileBuilder(
        user_store,
        mastery_store,
        kg_store,
        profile_store,
        StubEvidenceStore(),
    )


def _make_query(
    current_message="",
    group_style=None,
    recent_messages=None,
    resolved_kp_ids=None,
):
    """处理 `_make_query` 相关逻辑。"""
    return ProfileQuery(
        user_id="u1",
        username="alice",
        current_message=current_message,
        group_style=group_style,
        recent_messages=recent_messages or [],
        resolved_kp_ids=resolved_kp_ids or [],
    )


def _field(snapshot_section, field_name):
    """处理 `_field` 相关逻辑。"""
    for f in snapshot_section:
        if f.field == field_name:
            return f
    return None


def test_explicit_context_built():
    """验证 `explicit_context_built` 场景。"""
    builder = _make_builder()
    snapshot = builder.build(_make_query(current_message="hello"))

    fields = {f.field: f for f in snapshot.explicit_context}
    assert "major" in fields
    assert "grade" in fields
    assert "current_week" in fields
    assert "total_weeks" in fields
    assert fields["major"].value == "cs"
    assert fields["grade"].value == "大二"
    assert fields["current_week"].value == 3
    assert fields["total_weeks"].value == 18
    for f in snapshot.explicit_context:
        assert f.origin == ProfileOrigin.EXPLICIT_SETTING
        assert f.confidence == 1.0


def test_response_preferences_with_group_override():
    """验证 `response_preferences_with_group_override` 场景。"""
    builder = _make_builder()
    snapshot = builder.build(
        _make_query(current_message="hello", group_style="detailed")
    )

    style_field = _field(snapshot.response_preferences, "preferred_style")
    assert style_field is not None
    assert style_field.value == "detailed"
    assert style_field.origin == ProfileOrigin.EXPLICIT_SETTING


def test_group_override_does_not_change_user():
    """验证 `group_override_does_not_change_user` 场景。"""
    user = _make_user()
    builder = _make_builder(user=user)
    builder.build(_make_query(current_message="hello", group_style="detailed"))

    assert user.preferred_style == "concise"


def test_learning_state_uses_resolved_knowledge_point():
    """验证 `learning_state_uses_resolved_knowledge_point` 场景。"""
    kg_points = [{"id": "kp1", "name": "二叉树", "course": "数据结构"}]
    mastery_map = {"kp1": {"mastery_level": 40.0, "practice_count": 5}}
    builder = _make_builder(
        settings=_make_settings(learning=True),
        mastery_map=mastery_map,
        kg_points=kg_points,
    )
    snapshot = builder.build(
        _make_query(
            current_message="二叉树的遍历怎么做",
            resolved_kp_ids=["kp1"],
        )
    )

    assert len(snapshot.relevant_learning_state) >= 1
    kp_field = _field(snapshot.relevant_learning_state, "knowledge.kp1")
    assert kp_field is not None
    assert kp_field.origin == ProfileOrigin.DERIVED_LEARNING_STATE
    assert kp_field.value["mastery"]["has_record"] is True
    assert kp_field.value["mastery"]["level"] == 40.0
    assert kp_field.value["mastery"]["practice_count"] == 5


def test_learning_state_empty_no_match():
    """验证 `learning_state_empty_no_match` 场景。"""
    kg_points = [{"id": "kp1", "name": "二叉树", "course": "数据结构"}]
    builder = _make_builder(
        settings=_make_settings(learning=True),
        kg_points=kg_points,
    )
    snapshot = builder.build(_make_query(current_message="deploy fastapi"))

    assert snapshot.relevant_learning_state == []


def test_learning_state_disabled():
    """验证 `learning_state_disabled` 场景。"""
    kg_points = [{"id": "kp1", "name": "二叉树", "course": "数据结构"}]
    mastery_map = {"kp1": {"mastery_level": 40.0, "practice_count": 5}}
    builder = _make_builder(
        settings=_make_settings(learning=False),
        mastery_map=mastery_map,
        kg_points=kg_points,
    )
    snapshot = builder.build(
        _make_query(
            current_message="二叉树的遍历怎么做",
            resolved_kp_ids=["kp1"],
        )
    )

    assert snapshot.relevant_learning_state == []


def test_profile_disabled_returns_empty_prompt_snapshot():
    """验证 `profile_disabled_returns_empty_prompt_snapshot` 场景。"""
    user = _make_user()
    user.profile_enabled = False
    builder = _make_builder(user=user)

    snapshot = builder.build(_make_query(current_message="二叉树"))

    assert snapshot.to_prompt_json() == "{}"


def test_core_memory_is_not_automatically_promoted_into_profile():
    """验证 `core_memory_is_not_automatically_promoted_into_profile` 场景。"""
    memories = [
        {"id": "m1", "category": "language", "content": "python"},
    ]
    builder = _make_builder(
        settings=_make_settings(inferred=True),
        memories=memories,
    )
    snapshot = builder.build(_make_query(current_message="hello"))

    # Raw CoreMemory must be fetched only through memory tools on demand.
    assert snapshot.inferred_patterns == []

def test_inferred_patterns_disabled():
    """验证 `inferred_patterns_disabled` 场景。"""
    memories = [
        {"id": "m1", "category": "language", "content": "python"},
    ]
    builder = _make_builder(
        settings=_make_settings(inferred=False),
        memories=memories,
    )
    snapshot = builder.build(_make_query(current_message="hello"))

    assert snapshot.inferred_patterns == []


def test_suppressed_fields_excluded():
    """验证 `suppressed_fields_excluded` 场景。"""
    memories = [
        {"id": "m1", "category": "language", "content": "python"},
    ]
    suppressed = [{"field_key": "preferred_code_language"}]
    builder = _make_builder(
        settings=_make_settings(inferred=True),
        memories=memories,
        suppressed=suppressed,
    )
    snapshot = builder.build(_make_query(current_message="hello"))

    assert _field(snapshot.inferred_patterns, "preferred_code_language") is None


def test_explicit_overrides_inferred_for_style():
    """验证 `explicit_overrides_inferred_for_style` 场景。"""
    memories = [
        {"id": "m1", "category": "preference", "content": "用户喜欢详细回答"},
    ]
    builder = _make_builder(
        settings=_make_settings(inferred=True),
        memories=memories,
    )
    snapshot = builder.build(_make_query(current_message="hello"))

    explicit_style = _field(snapshot.response_preferences, "preferred_style")
    assert explicit_style is not None
    assert explicit_style.origin == ProfileOrigin.EXPLICIT_SETTING
    assert explicit_style.confidence == 1.0
    # preferred_style is never produced by inferred patterns -> explicit wins
    assert _field(snapshot.inferred_patterns, "preferred_style") is None
