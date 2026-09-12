# backend/tests/test_learning_state_service.py

"""验证 `learning_state_service` 相关行为与回归场景。"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from backend.agent.learning.evidence_store import LearningEvidenceStore
from backend.agent.learning.learning_state_service import LearningStateService
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.mastery_store import MasteryStore
from backend.agent.memories.memory_models import ProfileQuery
from backend.agent.memories.profile_builder import ProfileBuilder
from backend.core.stores.profile_store import ProfileStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import UserRecord


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


def test_same_idempotency_key_does_not_double_count(tmp_path):
    """同一可信请求的工具重试只产生一条证据。"""
    service, mastery, evidence = _service(tmp_path)
    first = service.record_event(
        user_name="alice",
        kp_id="DP",
        activity_type="practice",
        correct=True,
        idempotency_key="request-1:event-1",
    )
    second = service.record_event(
        user_name="alice",
        kp_id="DP",
        activity_type="practice",
        correct=True,
        idempotency_key="request-1:event-1",
    )

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert mastery.get("alice", "dynamic_programming")["practice_count"] == 1
    assert evidence.get_summary(
        "alice", kp_id="dynamic_programming"
    )["evidence_count"] == 1


def test_invalid_activity_type_is_rejected(tmp_path):
    """Tool schema 之外的活动类型不能污染学习状态。"""
    service, _, _ = _service(tmp_path)
    with pytest.raises(ValueError, match="activity_type"):
        service.record_event(
            user_name="alice",
            kp_id="DP",
            activity_type="invented",
            correct=True,
        )


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


def _service_with_profile(tmp_path):
    """搭建与 webAPI.create_app 一致的 service + profile_builder 装配。"""
    kg = KnowledgeGraphStore(tmp_path / "kg.db")
    kg.add_point("链表", "链表", "数据结构", 0.08)
    mastery = MasteryStore(tmp_path / "mastery.db")
    evidence = LearningEvidenceStore(tmp_path / "evidence.db")
    user_store = UserStore(tmp_path / "users.db")
    assert user_store.create(
        UserRecord(id="student-1", username="carol", password_hash="h", status="active")
    )
    profile_builder = ProfileBuilder(
        user_store=user_store,
        mastery_store=mastery,
        kg_store=kg,
        profile_store=ProfileStore(tmp_path / "profile.db"),
        evidence_store=evidence,
    )
    service = LearningStateService(
        kg_store=kg,
        mastery_store=mastery,
        evidence_store=evidence,
    )
    service.register_profile_invalidator(profile_builder.invalidate_by_username)
    return service, profile_builder, mastery


def test_real_evidence_invalidates_cached_profile_immediately(tmp_path):
    """真实学习证据写入后，无需等待 60 秒 TTL 即可重建最新学情画像。"""
    service, builder, _ = _service_with_profile(tmp_path)
    query = ProfileQuery(
        user_id="student-1",
        username="carol",
        current_message="讲讲链表",
        resolved_kp_ids=["链表"],
    )
    first = builder.build(query)
    first_state = first.relevant_learning_state[0].value
    assert first_state["mastery"]["has_record"] is False
    assert first_state["mastery"]["status"] == "unseen"
    # 画像缓存已建立：同一 query 在 TTL 内命中缓存，返回同一快照。
    assert builder.build(query) is first

    service.record_event(
        user_name="carol",
        kp_id="链表",
        activity_type="practice",
        correct=False,
        independent=True,
    )

    # 不等待 TTL：下一次 build 必须立即看到更新后的学情，而不是旧缓存。
    second = builder.build(query)
    assert second is not first
    second_state = second.relevant_learning_state[0].value
    assert second_state["mastery"]["has_record"] is True
    assert second_state["mastery"]["level"] < 50
    assert second_state["mastery"]["practice_count"] == 1
    assert second_state["evidence"]["count"] == 1


def test_profile_invalidator_fires_only_for_new_evidence(tmp_path):
    """真实写入触发画像失效回调；幂等重试不重复触发；回调异常不影响写入。"""
    service, mastery, _ = _service(tmp_path)
    calls: list[str] = []
    service.register_profile_invalidator(calls.append)

    service.record_event(
        user_name="alice",
        kp_id="DP",
        activity_type="practice",
        correct=True,
        idempotency_key="request-1:event-1",
    )
    assert calls == ["alice"]

    # 幂等重试（duplicate）没有产生新的学习状态更新，不应再次失效缓存。
    service.record_event(
        user_name="alice",
        kp_id="DP",
        activity_type="practice",
        correct=True,
        idempotency_key="request-1:event-1",
    )
    assert calls == ["alice"]

    def _boom(user_name: str) -> None:
        raise RuntimeError("invalidator crashed")

    service.register_profile_invalidator(_boom)
    result = service.record_event(
        user_name="alice",
        kp_id="DP",
        activity_type="practice",
        correct=False,
    )
    assert result["duplicate"] is False
    assert calls == ["alice", "alice"]
    assert mastery.get("alice", "dynamic_programming")["practice_count"] == 2
