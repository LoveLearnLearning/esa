"""Learning Tool adapter contracts."""

from types import SimpleNamespace

from backend.agent.learning.evidence_store import LearningEvidenceStore
from backend.agent.learning.learning_state_service import LearningStateService
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.mastery_store import MasteryStore
from backend.agent.tools.context import AgentRuntimeDependencies
from backend.agent.tools.learning.runtime import execute_learning_tool


def _runtime(tmp_path):
    kg = KnowledgeGraphStore(tmp_path / "kg.db")
    kg.add_point("dynamic_programming", "动态规划", "算法", 0.9)
    kg.add_alias("DP", "dynamic_programming")
    mastery = MasteryStore(tmp_path / "mastery.db")
    evidence = LearningEvidenceStore(tmp_path / "evidence.db")
    service = LearningStateService(
        kg_store=kg,
        mastery_store=mastery,
        evidence_store=evidence,
    )
    context = SimpleNamespace(
        runtime_dependencies=AgentRuntimeDependencies(
            knowledge_graph_store=kg,
            mastery_store=mastery,
            learning_evidence_store=evidence,
            learning_state_service=service,
        ),
        username="alice",
        user_id="u1",
        request_id="request-1",
        conversation_mode="normal",
        total_weeks=None,
    )
    return context, mastery, evidence


def test_learning_reads_resolve_registered_aliases(tmp_path):
    context, _, _ = _runtime(tmp_path)
    execute_learning_tool(
        context,
        "record_learning_evidence",
        {"kp_id": "DP", "activity_type": "practice", "correct": True},
    )

    result = execute_learning_tool(context, "get_mastery_level", {"kp_id": "DP"})

    assert result["has_record"] is True
    assert result["kp_id"] == "dynamic_programming"


def test_learning_write_retries_are_idempotent_per_request(tmp_path):
    context, mastery, evidence = _runtime(tmp_path)
    arguments = {
        "kp_id": "DP",
        "activity_type": "practice",
        "correct": True,
        "independent": True,
    }

    first = execute_learning_tool(
        context, "record_learning_evidence", arguments
    )
    second = execute_learning_tool(
        context, "record_learning_evidence", arguments
    )

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert mastery.get("alice", "dynamic_programming")["practice_count"] == 1
    assert evidence.get_summary(
        "alice", kp_id="dynamic_programming"
    )["evidence_count"] == 1


def test_legacy_and_canonical_practice_writes_share_the_same_event_key(tmp_path):
    context, mastery, evidence = _runtime(tmp_path)

    first = execute_learning_tool(
        context,
        "record_answer",
        {"kp_id": "DP", "correct": True, "confidence": 1.0},
    )
    second = execute_learning_tool(
        context,
        "record_learning_evidence",
        {
            "kp_id": "DP",
            "activity_type": "practice",
            "correct": True,
            "evidence_reliability": 1.0,
        },
    )

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert mastery.get("alice", "dynamic_programming")["practice_count"] == 1
    assert evidence.get_summary(
        "alice", kp_id="dynamic_programming"
    )["evidence_count"] == 1


def test_evidence_summary_only_requires_the_evidence_store(tmp_path):
    evidence = LearningEvidenceStore(tmp_path / "evidence.db")
    context = SimpleNamespace(
        runtime_dependencies=AgentRuntimeDependencies(
            learning_evidence_store=evidence
        ),
        username="alice",
        conversation_mode="normal",
    )

    result = execute_learning_tool(
        context, "get_learning_evidence_summary", {}
    )

    assert result["allowed"] is True
    assert result["evidence_count"] == 0


def test_legacy_boolean_string_is_not_coerced_by_python_truthiness(tmp_path):
    context, mastery, _ = _runtime(tmp_path)

    execute_learning_tool(
        context,
        "record_answer",
        {"kp_id": "DP", "correct": "false", "confidence": 1.0},
    )

    state = mastery.get("alice", "dynamic_programming")
    assert state["correct_count"] == 0


def test_canonical_boolean_strings_are_parsed_strictly(tmp_path):
    context, mastery, evidence = _runtime(tmp_path)

    execute_learning_tool(
        context,
        "record_learning_evidence",
        {
            "kp_id": "DP",
            "activity_type": "practice",
            "correct": "false",
            "independent": "false",
        },
    )

    state = mastery.get("alice", "dynamic_programming")
    assert state["correct_count"] == 0
    summary = evidence.get_summary("alice", kp_id="dynamic_programming")
    assert summary["independent_rate"] == 0.0
