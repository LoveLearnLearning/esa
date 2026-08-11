"""Pure Student Model V2 algorithms.

This module deliberately has no storage, web, context, or model dependencies.
Mastery models long-term understanding; retention is computed separately from
elapsed time and never written back into mastery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import exp, log, sqrt


@dataclass(frozen=True)
class EvidenceSignal:
    performance: float | None
    quality: float


class StudentModel:
    MIN_MASTERY = 5.0
    MAX_MASTERY = 98.0
    PRIOR_MASTERY = 50.0

    INITIAL_STABILITY_DAYS = 4.0
    MIN_STABILITY_DAYS = 1.5
    MAX_STABILITY_DAYS = 180.0
    REVIEW_THRESHOLD = 0.65

    ACTIVITY_FACTORS = {
        "practice": 1.00,
        "homework": 1.00,
        "retrieval": 1.05,
        "review": 0.95,
        "teach_back": 1.08,
        "transfer": 1.10,
        "hint": 0.75,
    }

    @staticmethod
    def clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

    @classmethod
    def evidence_signal(
        cls,
        *,
        activity_type: str,
        correct: bool | None,
        evidence_reliability: float,
        hint_level: int,
        attempts: int,
        independent: bool | None,
        recall_score: float | None,
        explanation_score: float | None,
        transfer_score: float | None,
    ) -> EvidenceSignal:
        weighted: list[tuple[float, float]] = []
        if correct is not None:
            weighted.append((1.0 if correct else 0.0, 0.55))
        if recall_score is not None:
            weighted.append((cls.clamp(recall_score, 0.0, 1.0), 0.15))
        if explanation_score is not None:
            weighted.append((cls.clamp(explanation_score, 0.0, 1.0), 0.15))
        if transfer_score is not None:
            weighted.append((cls.clamp(transfer_score, 0.0, 1.0), 0.15))

        if weighted:
            total_weight = sum(weight for _, weight in weighted)
            performance = sum(
                value * weight for value, weight in weighted
            ) / total_weight
        else:
            performance = None

        reliability = cls.clamp(evidence_reliability, 0.0, 1.0)
        normalized_hint = max(0, min(5, int(hint_level)))
        normalized_attempts = max(1, int(attempts))
        hint_factor = max(0.40, 1.0 - 0.12 * normalized_hint)
        independence_factor = 0.72 if independent is False else 1.0
        attempt_factor = 1.0 / sqrt(normalized_attempts)
        activity_factor = cls.ACTIVITY_FACTORS.get(activity_type.strip(), 1.0)
        quality = (
            reliability
            * hint_factor
            * independence_factor
            * attempt_factor
            * activity_factor
        )
        return EvidenceSignal(
            performance=performance,
            quality=cls.clamp(quality, 0.05, 1.0),
        )

    @classmethod
    def update_mastery(
        cls,
        *,
        mastery: float,
        evidence_weight: float,
        signal: EvidenceSignal,
    ) -> tuple[float, float]:
        if signal.performance is None:
            return mastery, evidence_weight
        current = cls.clamp(mastery, cls.MIN_MASTERY, cls.MAX_MASTERY)
        base_alpha = 0.22 if signal.performance >= 0.5 else 0.18
        alpha = (
            base_alpha
            * signal.quality
            / sqrt(1.0 + max(0.0, evidence_weight) / 4.0)
        )
        target = 100.0 * signal.performance
        updated = current + alpha * (target - current)
        return (
            cls.clamp(updated, cls.MIN_MASTERY, cls.MAX_MASTERY),
            max(0.0, evidence_weight) + signal.quality,
        )

    @classmethod
    def update_stability(
        cls,
        *,
        stability_days: float,
        mastery: float,
        signal: EvidenceSignal,
    ) -> float:
        if signal.performance is None:
            return stability_days
        if signal.performance >= 0.80:
            factor = 1.0 + 0.55 * signal.quality * (0.5 + mastery / 100.0)
        elif signal.performance >= 0.50:
            factor = 1.0 + 0.20 * signal.quality
        else:
            factor = 1.0 - 0.25 * signal.quality
        return cls.clamp(
            stability_days * factor,
            cls.MIN_STABILITY_DAYS,
            cls.MAX_STABILITY_DAYS,
        )

    @staticmethod
    def evidence_confidence(evidence_weight: float) -> float:
        return 1.0 - exp(-max(0.0, evidence_weight) / 3.5)

    @staticmethod
    def retention(
        *,
        last_practiced_at: str,
        stability_days: float,
        now: datetime | None = None,
    ) -> float:
        current = now or datetime.now()
        last = datetime.fromisoformat(last_practiced_at)
        if current.tzinfo is not None and last.tzinfo is None:
            current = current.replace(tzinfo=None)
        elif current.tzinfo is None and last.tzinfo is not None:
            current = current.replace(tzinfo=last.tzinfo)
        days = max(0.0, (current - last).total_seconds() / 86400.0)
        return 2.0 ** (-days / max(0.01, stability_days))

    @classmethod
    def days_until_threshold(
        cls,
        *,
        stability_days: float,
        threshold: float | None = None,
    ) -> float:
        normalized = cls.clamp(
            cls.REVIEW_THRESHOLD if threshold is None else threshold,
            0.01,
            0.99,
        )
        return -stability_days * log(normalized) / log(2.0)

    @staticmethod
    def status(mastery: float | None, confidence: float) -> str:
        if mastery is None or confidence <= 0.0:
            return "unseen"
        if mastery < 40.0:
            return "weak"
        if mastery < 70.0:
            return "learning"
        if mastery < 85.0:
            return "good"
        return "mastered"
