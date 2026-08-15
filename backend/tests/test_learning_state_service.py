# backend/tests/test_learning_state_service.py

"""验证 `learning_state_service` 相关行为与回归场景。"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from backend.agent.learning.evidence_store import LearningEvidenceStore
from backend.agent.learning.learning_state_service import LearningStateService
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.mastery_store import MasteryStore


def _service(tmp_path):
    """处理 `_service` 相关逻辑。"""
    kg = KnowledgeGraphStore(tmp_path / "kg.db")
    kg.add_point("dynamic_programming", "动态规划", "算法", 0.9)
    kg.add_alias("DP", "dynamic_programming")
    mastery = MasteryStore(tmp_path / "mastery.db")
    evidence = LearningEvidenceStore(tmp_path / "evidence.db")
    return LearningStateService(
        kg_store=kg,
        mastery_store=mastery,
        evidence_store=evidence,
    ), mastery, evidence


def test_canonical_name_and_alias_are_resolved(tmp_path):
    """验证 `canonical_name_and_alias_are_resolved` 场景。"""
    service, _, _ = _service(tmp_path)
    assert service.resolve_kp_id("dynamic_programming") == "dynamic_programming"
    assert service.resolve_kp_id("动态规划") == "dynamic_programming"
    assert service.resolve_kp_id("DP") == "dynamic_programming"


def test_unknown_knowledge_point_is_rejected(tmp_path):
    """验证 `unknown_knowledge_point_is_rejected` 场景。"""
    service, _, _ = _service(tmp_path)
    with pytest.raises(ValueError, match="未知知识点"):
        service.record_event(
            user_name="alice",
            kp_id="invented-point",
            activity_type="practice",
            correct=True,
        )


def test_one_event_updates_evidence_and_mastery(tmp_path):
    """验证 `one_event_updates_evidence_and_mastery` 场景。"""
    service, mastery, evidence = _service(tmp_path)
    result = service.record_event(
        user_name="alice",
        kp_id="DP",
        activity_type="practice",
        correct=True,
        independent=True,
    )
    assert result["evidence"]["kp_id"] == "dynamic_programming"
    assert result["state"]["mastery_level"] > 50
    assert mastery.get("alice", "dynamic_programming")["practice_count"] == 1
    assert evidence.get_summary(
        "alice", kp_id="dynamic_programming"
    )["evidence_count"] == 1


def test_mastery_is_not_changed_when_only_time_passes(tmp_path):
    """验证 `mastery_is_not_changed_when_only_time_passes` 场景。"""
    service, mastery, _ = _service(tmp_path)
    service.record_event(
        user_name="alice",
        kp_id="DP",
        activity_type="practice",
        correct=True,
    )
    before = mastery.get("alice", "dynamic_programming")
    old = (datetime.now() - timedelta(days=30)).isoformat()
    with sqlite3.connect(mastery.database_path) as connection:
        connection.execute(
            "UPDATE user_mastery SET last_practiced_at = ? WHERE user_name = ?",
            (old, "alice"),
        )
    after = mastery.get("alice", "dynamic_programming")
    assert after["mastery_level"] == before["mastery_level"]
    assert after["retention"] < before["retention"]
