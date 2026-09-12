# backend/agent/learning/learning_state_service.py

"""Single write path for learning evidence and Student Model state."""

from __future__ import annotations

import logging
from typing import Callable

from backend.agent.learning.evidence_store import LearningEvidenceStore
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.mastery_store import MasteryStore

logger = logging.getLogger(__name__)


class LearningStateService:
    """提供 `learning state service` 领域服务。"""
    def __init__(
        self,
        *,
        kg_store: KnowledgeGraphStore,
        mastery_store: MasteryStore,
        evidence_store: LearningEvidenceStore,
    ) -> None:
        """初始化 `LearningStateService` 实例。"""
        self.kg_store = kg_store
        self.mastery_store = mastery_store
        self.evidence_store = evidence_store
        self._profile_invalidators: list[Callable[[str], None]] = []

    def register_profile_invalidator(
        self,
        invalidator: Callable[[str], None],
    ) -> None:
        """注册画像缓存失效回调，回调参数为 user_name。

        只有真实且可评价的学习证据成功写入并更新 Student Model 后才会触发；
        出题、提示、普通聊天等不产生学习证据的行为不会调用本服务的写入路径，
        因此不会误触发失效。
        """
        self._profile_invalidators.append(invalidator)

    def _invalidate_profile_cache(self, user_name: str) -> None:
        """学习状态真实更新后，通知所有画像缓存失效回调。"""
        for invalidator in self._profile_invalidators:
            try:
                invalidator(user_name)
            except Exception:
                logger.warning(
                    "画像缓存失效回调执行失败 user_name=%s", user_name, exc_info=True
                )

    def resolve_kp_id(self, raw_kp_id: str) -> str:
        """解析 `kp id` 相关数据。"""
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
        idempotency_key: str | None = None,
    ) -> dict:
        """处理 `record_event` 相关逻辑。

        Args:
            user_name: str => `user_name` 参数。
            kp_id: str => kp ID。
            activity_type: str => `activity_type` 参数。
            correct: bool | None => `correct` 参数。
            self_confidence: float | None => `self_confidence` 参数。
            evidence_reliability: float => `evidence_reliability` 参数。
            hint_level: int => `hint_level` 参数。
            attempts: int => `attempts` 参数。
            independent: bool | None => `independent` 参数。
            recall_score: float | None => `recall_score` 参数。
            explanation_score: float | None => `explanation_score` 参数。
            transfer_score: float | None => `transfer_score` 参数。
            error_type: str | None => `error_type` 参数。
            misconception: str | None => `misconception` 参数。
            idempotency_key: 同一可信请求内重试时使用的幂等键。

        Returns:
            dict => 处理结果。
        """
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
            idempotency_key=idempotency_key,
        )
        if evidence.get("duplicate"):
            return {
                "evidence": evidence,
                "state": self.mastery_store.get(user_name, resolved_kp_id),
                "duplicate": True,
            }
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
        # 真实学习证据已写入且 Student Model 已更新：立即失效该用户的画像缓存，
        # 保证下一轮 ProfileBuilder.build 读取最新学情而不是 60 秒 TTL 内的旧快照。
        self._invalidate_profile_cache(user_name)
        return {"evidence": evidence, "state": state, "duplicate": False}
