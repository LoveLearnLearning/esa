import inspect
from types import SimpleNamespace

from backend.agent.memories.memory_models import ProfileOrigin
from backend.agent.memories.profile_builder import ProfileBuilder


class StubProfileStore:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def list_dimensions(self, user_id, status_filter=None):
        self.calls.append((user_id, status_filter))
        return self.rows if status_filter == "active" else []


def test_profile_builder_has_no_core_memory_dependency():
    signature = inspect.signature(ProfileBuilder.__init__)
    assert "core_memory" not in signature.parameters

    source = inspect.getsource(ProfileBuilder._build_inferred_patterns)
    assert "_core_memory" not in source
    assert "status_filter=\"active\"" in source
    assert "ProfileStore" in source


def test_inferred_profile_reads_only_structured_profile_store():
    store = StubProfileStore(
        [
            {
                "field_key": "preferred_code_language",
                "value": "python",
                "origin": "inferred_pattern",
                "confidence": 0.7,
                "source_memory_ids": ["m1"],
                "last_confirmed_at": None,
            },
            {
                # 非推断/确认来源不应混入 inferred_patterns
                "field_key": "major",
                "value": "cs",
                "origin": "explicit_setting",
                "confidence": 1.0,
                "source_memory_ids": [],
                "last_confirmed_at": None,
            },
        ]
    )

    builder = object.__new__(ProfileBuilder)
    builder._profile_store = store

    fields = builder._build_inferred_patterns(
        SimpleNamespace(id="u1"),
        SimpleNamespace(inferred_profile_enabled=True),
    )

    assert store.calls == [("u1", "active")]
    assert len(fields) == 1
    assert fields[0].field == "preferred_code_language"
    assert fields[0].value == "python"
    assert fields[0].origin == ProfileOrigin.INFERRED_PATTERN
