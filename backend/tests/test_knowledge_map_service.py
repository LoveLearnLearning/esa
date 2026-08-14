from backend.agent.learning.evidence_store import LearningEvidenceStore
from backend.agent.learning.knowledge_map_service import KnowledgeMapService
from backend.agent.learning.learning_state_service import LearningStateService
from backend.agent.memories.kg_loader import load_into_store
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
    course_node = next(node for node in result["nodes"] if node["node_type"] == "course")
    assert course_node["name"] == "课程"
    assert course_node["level"] == 0
    assert result["edges"] == [
        {"from": course_node["id"], "to": "base", "type": "course_root"},
        {"from": "base", "to": "advanced", "type": "prerequisite"},
    ]
    assert nodes["advanced"]["level"] > nodes["base"]["level"]


def test_course_node_connects_multiple_components_and_cycles(tmp_path):
    kg = KnowledgeGraphStore(tmp_path / "kg-components.db")
    kg.add_point("a-root", "A 根", "课程", 0.4)
    kg.add_point("a-child", "A 子", "课程", 0.4)
    kg.add_point("b-root", "B 根", "课程", 0.4)
    kg.add_point("b-child", "B 子", "课程", 0.4)
    kg.add_point("cycle-a", "环 A", "课程", 0.4)
    kg.add_point("cycle-b", "环 B", "课程", 0.4)
    kg.add_prerequisite("a-child", "a-root")
    kg.add_prerequisite("b-child", "b-root")
    kg.add_prerequisite("cycle-a", "cycle-b")
    kg.add_prerequisite("cycle-b", "cycle-a")
    service = KnowledgeMapService(
        kg_store=kg,
        mastery_store=MasteryStore(tmp_path / "mastery-components.db"),
        evidence_store=LearningEvidenceStore(tmp_path / "evidence-components.db"),
    )

    result = service.get_course_map(user_name="alice", course="课程")
    course_node = next(node for node in result["nodes"] if node["node_type"] == "course")
    course_edges = {
        edge["to"] for edge in result["edges"] if edge["type"] == "course_root"
    }
    assert course_edges == {"a-root", "b-root", "cycle-a"}
    assert {node["id"] for node in result["nodes"]} == {
        course_node["id"],
        "a-root",
        "a-child",
        "b-root",
        "b-child",
        "cycle-a",
        "cycle-b",
    }


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


def test_course_alias_resolves_to_canonical_course(tmp_path):
    store = KnowledgeGraphStore(tmp_path / "kg-with-aliases.db")
    load_into_store(store)

    assert store.resolve_course_name("数字电路技术") == "数字逻辑与数字电路"
    assert store.resolve_course_name("  数字 电路技术 ") == "数字逻辑与数字电路"
    assert store.resolve_course_name("不存在的课程") is None
