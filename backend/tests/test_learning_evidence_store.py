# backend/tests/test_learning_evidence_store.py

"""验证 `learning_evidence_store` 相关行为与回归场景。"""

from backend.agent.learning.evidence_store import LearningEvidenceStore


def test_learning_evidence_summary_tracks_process_not_only_correctness(tmp_path):
    """验证 `learning_evidence_summary_tracks_process_not_only_correctness` 场景。"""
    store = LearningEvidenceStore(tmp_path / "evidence.db")

    store.record(
        user_name="alice",
        kp_id="binary_search",
        activity_type="practice",
        correct=True,
        self_confidence=0.9,
        hint_level=0,
        independent=True,
        transfer_score=0.8,
    )
    store.record(
        user_name="alice",
        kp_id="binary_search",
        activity_type="homework",
        correct=False,
        self_confidence=0.8,
        hint_level=3,
        attempts=2,
        independent=False,
        error_type="conceptual",
        misconception="混用了闭区间与左闭右开区间的更新规则",
    )

    summary = store.get_summary("alice", kp_id="binary_search")

    assert summary["evidence_count"] == 2
    assert summary["correct_rate"] == 0.5
    assert summary["avg_self_confidence"] == 0.85
    assert summary["avg_hint_level"] == 1.5
    assert summary["independent_rate"] == 0.5
    assert summary["error_type_counts"] == {"conceptual": 1}
    assert summary["recent_misconceptions"] == [
        "混用了闭区间与左闭右开区间的更新规则"
    ]


def test_learning_evidence_rejects_unknown_error_type(tmp_path):
    """验证 `learning_evidence_rejects_unknown_error_type` 场景。"""
    store = LearningEvidenceStore(tmp_path / "evidence.db")

    try:
        store.record(
            user_name="alice",
            kp_id="k1",
            activity_type="practice",
            error_type="personality_problem",
        )
    except ValueError as exc:
        assert "error_type" in str(exc)
    else:
        raise AssertionError("unknown error_type should be rejected")
