# backend/tests/test_profile_core_memory_separation.py

"""验证 `profile_core_memory_separation` 相关行为与回归场景。"""

import inspect
from types import SimpleNamespace

from backend.agent.memories.memory_models import ProfileOrigin
from backend.agent.memories.profile_builder import ProfileBuilder


class StubProfileStore:
    """封装 `stub profile store` 数据持久化操作。"""
    def __init__(self, rows):
        """初始化 `StubProfileStore` 实例。"""
        self.rows = rows
        self.calls = []

    def list_dimensions(self, user_id, status_filter=None):
        """列出 `dimensions` 相关数据。

        Args:
            user_id: object => 用户 ID。
            status_filter: object => `status_filter` 参数。

        Returns:
            object => 处理结果。
        """
        self.calls.append((user_id, status_filter))
        return self.rows if status_filter == "active" else []


def test_profile_builder_has_no_core_memory_dependency():
    """验证 `profile_builder_has_no_core_memory_dependency` 场景。"""
    signature = inspect.signature(ProfileBuilder.__init__)
    assert "core_memory" not in signature.parameters

    source = inspect.getsource(ProfileBuilder._build_inferred_patterns)
    assert "_core_memory" not in source
    assert "status_filter=\"active\"" in source
    assert "ProfileStore" in source


def test_inferred_profile_reads_only_structured_profile_store():
    """验证 `inferred_profile_reads_only_structured_profile_store` 场景。"""
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
