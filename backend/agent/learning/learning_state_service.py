"""Single write path for learning evidence and Student Model state."""

from __future__ import annotations

from backend.agent.learning.evidence_store import LearningEvidenceStore
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.mastery_store import MasteryStore


class LearningStateService:
    def __init__(
        self,
        *,
        kg_store: KnowledgeGraphStore,
        mastery_store: MasteryStore,
        evidence_store: LearningEvidenceStore,
    ) -> None:
        self.kg_store = kg_store
        self.mastery_store = mastery_store
        self.evidence_store = evidence_store

    def resolve_kp_id(self, raw_kp_id: str) -> str:
        resolved = self.kg_store.resolve_kp_id(raw_kp_id)
        if resolved is None:
            raise ValueError(f"未知知识点 {raw_kp_id!r}，禁止写入学习状态")
        return resolved

    def record_event(
        self,
        *,
        user_name: str,
        kp_id: str,
        activity_type: str,
        correct: bool | None = None,
        self_confidence: float | None = None,
        evidence_reliability: float = 1.0,
        hint_level: int = 0,
        attempts: int = 1,
        independent: bool | None = None,
        recall_score: float | None = None,
        explanation_score: float | None = None,
        transfer_score: float | None = None,
        error_type: str | None = None,
        misconception: str | None = None,
    ) -> dict:
        resolved_kp_id = self.resolve_kp_id(kp_id)
        evidence = self.evidence_store.record(
            user_name=user_name,
            kp_id=resolved_kp_id,
            activity_type=activity_type,
            correct=correct,
            self_confidence=self_confidence,
            evidence_reliability=evidence_reliability,
            hint_level=hint_level,
            attempts=attempts,
            independent=independent,
            recall_score=recall_score,
            explanation_score=explanation_score,
            transfer_score=transfer_score,
            error_type=error_type,
            misconception=misconception,
        )
        state = self.mastery_store.apply_evidence(
            user_name=user_name,
            kp_id=resolved_kp_id,
            activity_type=activity_type,
            correct=correct,
            evidence_reliability=evidence_reliability,
            hint_level=hint_level,
            attempts=attempts,
            independent=independent,
            recall_score=recall_score,
            explanation_score=explanation_score,
            transfer_score=transfer_score,
        )
        return {"evidence": evidence, "state": state}
