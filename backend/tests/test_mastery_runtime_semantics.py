# backend/tests/test_mastery_runtime_semantics.py

"""验证 `mastery_runtime_semantics` 相关行为与回归场景。"""

from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.tools.learning.mastery import EsaMasteryStore


def test_target_itself_is_not_returned_as_weak_prerequisite(tmp_path):
    """验证 `target_itself_is_not_returned_as_weak_prerequisite` 场景。"""
    kg = KnowledgeGraphStore(tmp_path / "kg.db")
    mastery = EsaMasteryStore(tmp_path / "mastery.db")

    assert kg.add_point("target", "目标知识", "课程")
    assert kg.add_point("prereq", "前置知识", "课程")
    assert kg.add_prerequisite("target", "prereq")

    # 默认掌握度 50，阈值设为 60：如果 depth=0 未过滤，
    # target 自己也会被错误地返回。
    weak = mastery.get_weak_prerequisites(
        user_name="alice",
        kp_id="target",
        kg_store=kg,
        mastery_threshold=60,
    )

    assert [item["kp_id"] for item in weak] == ["prereq"]
    assert all(item["depth"] > 0 for item in weak)
