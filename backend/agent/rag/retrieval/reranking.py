# backend/agent/rag/retrieval/reranking.py

"""

这个文件干什么：封装 RRF 候选的模型重排、阈值筛选和显式重叠 Chunk 去重。

直白点说就是：让模型重新判断候选相关性并筛选结果；模型出故障时就稳妥地沿用原来的融合顺序。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math

from ..chunk import Chunk
from ..inference import InferenceUnavailable
from .contracts import RankedItem, Reranker, RetrievalConfig
from .fusion import consolidate_overlaps


def aggregate_chunk_scores(scores: Sequence[float], method: str) -> float:
    """把同一文档的少量 chunk 分数聚合成文档级实验分数。"""

    values = [float(score) for score in scores]
    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("chunk scores must be non-empty and finite")
    if method == "max":
        return max(values)
    if method == "mean":
        return sum(values) / len(values)
    raise ValueError("aggregation method must be 'max' or 'mean'")


def blend_retrieval_and_reranker(
    candidates: Sequence[RankedItem],
    rerank_scores: Mapping[str, float],
    prior_weight: float,
) -> list[RankedItem]:
    """保留 retrieval prior，并把 ``[0, 1]`` reranker 分数作为低权重信号。"""

    if not 0 <= prior_weight <= 1:
        raise ValueError("prior_weight must be between zero and one")
    if prior_weight == 1:
        return list(candidates)
    if not candidates:
        return []
    prior_values = [float(item.score) for item in candidates]
    if any(not math.isfinite(value) for value in prior_values):
        raise ValueError("retrieval prior scores must be finite")
    low, high = min(prior_values), max(prior_values)
    span = high - low
    blended: list[tuple[int, RankedItem]] = []
    for rank, item in enumerate(candidates):
        prior = 1.0 if span == 0 else (item.score - low) / span
        rerank = float(rerank_scores[item.chunk_id])
        if not math.isfinite(rerank):
            raise ValueError("reranker scores must be finite")
        score = prior_weight * prior + (1.0 - prior_weight) * min(1.0, max(0.0, rerank))
        blended.append((rank, RankedItem(item.chunk_id, score)))
    blended.sort(key=lambda value: (-value[1].score, value[0], value[1].chunk_id))
    return [item for _rank, item in blended]


@dataclass(frozen=True)
class CandidateSelection:
    """重排阶段产生的排名、最终候选、分数和降级记录。"""

    ranking: tuple[RankedItem, ...]
    final_candidates: tuple[RankedItem, ...]
    rerank_scores: Mapping[str, float]
    degraded: tuple[str, ...]


@dataclass(frozen=True)
class CandidateReranker:
    """只负责候选重排、阈值过滤和重叠合并。"""

    chunks: Mapping[str, Chunk]
    reranker: Reranker | None
    config: RetrievalConfig

    def select(
        self,
        query: str,
        fused: Sequence[RankedItem],
    ) -> CandidateSelection:
        """从 RRF 排名产生最终候选；模型故障时保留 RRF 顺序。"""

        candidates = list(fused[: self.config.rerank_limit])
        rerank_scores: dict[str, float] = {}
        degraded: list[str] = []

        if self.config.reranker_enabled and self.reranker is not None and candidates:
            try:
                documents = [
                    self.chunks[item.chunk_id].dense_text for item in candidates
                ]
                scores: list[float] = []
                for start in range(0, len(documents), self.config.reranker_batch_size):
                    scores.extend(
                        self.reranker.score(
                            query,
                            documents[start : start + self.config.reranker_batch_size],
                        )
                    )
                if len(scores) != len(candidates):
                    raise ValueError("reranker output count does not match candidates")
                rerank_scores = {
                    item.chunk_id: score for item, score in zip(candidates, scores)
                }
                candidates = blend_retrieval_and_reranker(
                    candidates,
                    rerank_scores,
                    self.config.reranker_prior_weight,
                )
            except InferenceUnavailable as exc:
                degraded.append(f"reranker_unavailable:{type(exc).__name__}")
        else:
            degraded.append("reranker_disabled")

        if self.config.rerank_threshold is not None and rerank_scores:
            candidates = [
                item
                for item in candidates
                if item.score >= self.config.rerank_threshold
            ]

        ranking = tuple(candidates)
        final_candidates = tuple(
            consolidate_overlaps(candidates, self.chunks)[: self.config.final_limit]
        )
        return CandidateSelection(
            ranking=ranking,
            final_candidates=final_candidates,
            rerank_scores=rerank_scores,
            degraded=tuple(degraded),
        )
