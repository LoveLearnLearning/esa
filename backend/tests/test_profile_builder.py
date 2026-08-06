from backend.agent.memories.memory_models import ProfileOrigin, ProfileQuery
from backend.agent.memories.profile_builder import ProfileBuilder
from backend.core.utils.models import MemorySettings, UserRecord


class StubUserStore:
    def __init__(self, user, settings=None):
        self._user = user
        self._settings = settings

    def get_by_id(self, user_id):
        return self._user

    def get_memory_settings(self, user_id):
        return self._settings


class StubMasteryStore:
    def __init__(self, mastery_map=None, prereqs=None):
        self._mastery_map = mastery_map or {}  # kp_id -> dict
        self._prereqs = prereqs or []

    def get(self, user_name, kp_id):
        return self._mastery_map.get(kp_id)

    def get_weak_prerequisites(
        self, user_name, kp_id, kg_store, mastery_threshold=50.0, max_depth=5
    ):
        return self._prereqs


class StubKGStore:
    def __init__(self, points=None):
        self._points = points or []

    def list_all(self):
        return self._points


class StubCoreMemory:
    def __init__(self, memories=None):
        self._memories = memories or []

    def get_all(self, user_name):
        return self._memories


class StubProfileStore:
    def __init__(self, suppressed=None):
        self._suppressed = suppressed or []  # list of dicts with field_key
        self.upserts = []

    def list_dimensions(self, user_id, status_filter=None):
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
        self.upserts.append({"field_key": field_key, "value": value})
        return True

    def get_dimension(self, user_id, field_key):
        return None

    def suppress_dimension(self, user_id, field_key):
        return True


def _make_user():
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
    user = user or _make_user()
    user_store = StubUserStore(user, settings)
    mastery_store = StubMasteryStore(mastery_map, prereqs)
    kg_store = StubKGStore(kg_points)
    core_memory = StubCoreMemory(memories)
    profile_store = StubProfileStore(suppressed)
    return ProfileBuilder(user_store, mastery_store, kg_store, core_memory, profile_store)


def _make_query(current_message="", group_style=None, recent_messages=None):
    return ProfileQuery(
        user_id="u1",
        username="alice",
        current_message=current_message,
        group_style=group_style,
        recent_messages=recent_messages or [],
    )


def _field(snapshot_section, field_name):
    for f in snapshot_section:
        if f.field == field_name:
            return f
    return None


def test_explicit_context_built():
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
    builder = _make_builder()
    snapshot = builder.build(
        _make_query(current_message="hello", group_style="detailed")
    )

    style_field = _field(snapshot.response_preferences, "preferred_style")
    assert style_field is not None
    assert style_field.value == "detailed"
    assert style_field.origin == ProfileOrigin.EXPLICIT_SETTING


def test_group_override_does_not_change_user():
    user = _make_user()
    builder = _make_builder(user=user)
    builder.build(_make_query(current_message="hello", group_style="detailed"))

    assert user.preferred_style == "concise"


def test_learning_state_filtered_by_question():
    kg_points = [{"id": "kp1", "name": "二叉树"}]
    mastery_map = {"kp1": {"mastery_level": 40.0, "practice_count": 5}}
    builder = _make_builder(
        settings=_make_settings(learning=True),
        mastery_map=mastery_map,
        kg_points=kg_points,
    )
    snapshot = builder.build(_make_query(current_message="二叉树的遍历怎么做"))

    assert len(snapshot.relevant_learning_state) >= 1
    kp_field = _field(snapshot.relevant_learning_state, "kp1")
    assert kp_field is not None
    assert kp_field.origin == ProfileOrigin.DERIVED_LEARNING_STATE
    assert kp_field.value["mastery_level"] == 40.0
    assert kp_field.value["practice_count"] == 5


def test_learning_state_empty_no_match():
    kg_points = [{"id": "kp1", "name": "二叉树"}]
    builder = _make_builder(
        settings=_make_settings(learning=True),
        kg_points=kg_points,
    )
    snapshot = builder.build(_make_query(current_message="deploy fastapi"))

    assert snapshot.relevant_learning_state == []


def test_learning_state_disabled():
    kg_points = [{"id": "kp1", "name": "二叉树"}]
    mastery_map = {"kp1": {"mastery_level": 40.0, "practice_count": 5}}
    builder = _make_builder(
        settings=_make_settings(learning=False),
        mastery_map=mastery_map,
        kg_points=kg_points,
    )
    snapshot = builder.build(_make_query(current_message="二叉树的遍历怎么做"))

    assert snapshot.relevant_learning_state == []


def test_inferred_patterns_from_core_memory():
    memories = [
        {"id": "m1", "category": "language", "content": "python"},
    ]
    builder = _make_builder(
        settings=_make_settings(inferred=True),
        memories=memories,
    )
    snapshot = builder.build(_make_query(current_message="hello"))

    lang_field = _field(snapshot.inferred_patterns, "preferred_code_language")
    assert lang_field is not None
    assert lang_field.value == "python"
    assert lang_field.origin == ProfileOrigin.INFERRED_PATTERN
    assert lang_field.confidence == 0.7
    assert "m1" in lang_field.source_memory_ids


def test_inferred_patterns_disabled():
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
