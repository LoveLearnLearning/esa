from backend.agent.memories.core_memory import CoreMemory


def test_core_memory_no_longer_owns_prompt_builder(tmp_path):
    store = CoreMemory(tmp_path / "core.db")
    assert not hasattr(store, "build_context")


def test_core_memory_search_returns_only_relevant_limited_items(tmp_path):
    store = CoreMemory(tmp_path / "core.db")
    store.set("alice", "python_language", "用户更喜欢 Python 示例", "preference")
    store.set("alice", "current_project", "正在实现 ESA 学习 Agent", "project")
    store.set("alice", "response_style", "回答偏好简洁", "preference")

    results = store.search("alice", "Python", limit=2)

    assert len(results) == 1
    assert results[0]["memory_key"] == "python_language"


def test_core_memory_search_does_not_fallback_to_all_memories(tmp_path):
    store = CoreMemory(tmp_path / "core.db")
    store.set("alice", "python_language", "用户更喜欢 Python 示例", "preference")

    assert store.search("alice", "完全不存在的主题") == []
