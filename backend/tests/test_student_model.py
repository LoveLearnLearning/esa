# backend/tests/test_student_model.py

"""验证 `student_model` 相关行为与回归场景。"""

from datetime import datetime, timedelta

from backend.agent.learning.student_model import StudentModel


def _signal(**overrides):
    """处理 `_signal` 相关逻辑。"""
    values = {
        "activity_type": "practice",
        "correct": True,
        "evidence_reliability": 1.0,
        "hint_level": 0,
        "attempts": 1,
        "independent": True,
        "recall_score": None,
        "explanation_score": None,
        "transfer_score": None,
    }
    values.update(overrides)
    return StudentModel.evidence_signal(**values)


def test_strong_correct_evidence_increases_mastery():
    """验证 `strong_correct_evidence_increases_mastery` 场景。"""
    mastery, _ = StudentModel.update_mastery(
        mastery=50, evidence_weight=0, signal=_signal()
    )
    assert mastery > 60


def test_strong_wrong_evidence_decreases_mastery():
    """验证 `strong_wrong_evidence_decreases_mastery` 场景。"""
    mastery, _ = StudentModel.update_mastery(
        mastery=50, evidence_weight=0, signal=_signal(correct=False)
    )
    assert mastery < 42


def test_hint_attempts_and_dependence_reduce_quality():
    """验证 `hint_attempts_and_dependence_reduce_quality` 场景。"""
    strong = _signal()
    hinted = _signal(hint_level=3)
    retried = _signal(attempts=3)
    dependent = _signal(independent=False)
    assert hinted.quality < strong.quality
    assert retried.quality < strong.quality
    assert dependent.quality < strong.quality


def test_mastery_does_not_decay_but_retention_does():
    """验证 `mastery_does_not_decay_but_retention_does` 场景。"""
    mastery = 72.0
    last = datetime(2026, 1, 1, 12)
    before = StudentModel.retention(
        last_practiced_at=last.isoformat(), stability_days=4, now=last
    )
    after = StudentModel.retention(
        last_practiced_at=last.isoformat(),
        stability_days=4,
        now=last + timedelta(days=7),
    )
    assert mastery == 72.0
    assert after < before


def test_more_evidence_increases_confidence_and_correct_increases_stability():
    """验证 `more_evidence_increases_confidence_and_correct_increases_stability` 场景。"""
    assert StudentModel.evidence_confidence(5) > StudentModel.evidence_confidence(1)
    updated = StudentModel.update_stability(
        stability_days=4, mastery=61, signal=_signal()
    )
    assert updated > 4
