from backend.agent.learning.evidence_store import LearningEvidenceStore
from backend.agent.learning.knowledge_map_service import KnowledgeMapService
from backend.agent.learning.learning_state_service import LearningStateService
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.mastery_store import MasteryStore


def _stores(tmp_path):
    kg = KnowledgeGraphStore(tmp_path / "kg.db")
    kg.add_point("base", "基础", "课程", 0.4)
    kg.add_point("advanced", "进阶", "课程", 0.9)
    kg.add_prerequisite("advanced", "base")
    mastery = MasteryStore(tmp_path / "mastery.db")
    evidence = LearningEvidenceStore(tmp_path / "evidence.db")
    writer = LearningStateService(
        kg_store=kg,
        mastery_store=mastery,
        evidence_store=evidence,
    )
    service = KnowledgeMapService(
        kg_store=kg,
        mastery_store=mastery,
        evidence_store=evidence,
    )
    return writer, service


def test_course_map_has_unseen_semantics_and_forward_edge(tmp_path):
    _, service = _stores(tmp_path)
    result = service.get_course_map(user_name="alice", course="课程")
    nodes = {node["id"]: node for node in result["nodes"]}
    assert nodes["base"]["mastery_level"] is None
    assert nodes["base"]["status"] == "unseen"
    assert result["edges"] == [
        {"from": "base", "to": "advanced", "type": "prerequisite"}
    ]
    assert nodes["advanced"]["level"] > nodes["base"]["level"]


def test_courses_and_point_detail_reflect_learning_event(tmp_path):
    writer, service = _stores(tmp_path)
    writer.record_event(
        user_name="alice",
        kp_id="advanced",
        activity_type="practice",
        correct=False,
    )
    courses = service.get_courses(user_name="alice")["courses"]
    assert courses[0]["evaluated_points"] == 1
    detail = service.get_point_detail(user_name="alice", kp_id="advanced")
    assert detail["state"]["has_record"] is True
    assert detail["evidence_summary"]["evidence_count"] == 1
