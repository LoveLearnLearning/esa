# backend/agent/rag/retrieval/reranking.py

"""

这个文件干什么：封装 fusion 候选的模型重排、阈值筛选和显式重叠 Chunk 去重。

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


def rerank_by_score(
    candidates: Sequence[RankedItem],
    rerank_scores: Mapping[str, float],
) -> list[RankedItem]:
    """只按 Reranker 分数重排 fusion 已形成的候选池。

    Fusion 与 Reranker 是两个连续阶段，不混合不同量纲的分数；原始
    fusion 分数由上层单独保留，用于审计和离线分析。
    """

    if not candidates:
        return []
    reranked: list[tuple[int, RankedItem]] = []
    for rank, item in enumerate(candidates):
        rerank = float(rerank_scores[item.chunk_id])
        if not math.isfinite(rerank):
            raise ValueError("reranker scores must be finite")
        reranked.append((rank, RankedItem(item.chunk_id, rerank)))
    reranked.sort(key=lambda value: (-value[1].score, value[0], value[1].chunk_id))
    return [item for _rank, item in reranked]


@dataclass(frozen=True)
class CandidateSelection:
    """重排阶段产生的排名、最终候选、分数和降级记录。"""

    ranking: tuple[RankedItem, ...]
    final_candidates: tuple[RankedItem, ...]
    rerank_scores: Mapping[str, float]
    degraded: tuple[str, ...]
    reranker_applied: bool


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
        """从 fusion 排名产生最终候选；模型故障时保留 fusion 顺序。"""

        candidates = list(fused[: self.config.rerank_limit])
        rerank_scores: dict[str, float] = {}
        degraded: list[str] = []
        reranker_applied = False

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
                reranker_applied = True
                candidates = rerank_by_score(candidates, rerank_scores)
            except InferenceUnavailable as exc:
                degraded.append(f"reranker_unavailable:{type(exc).__name__}")
        if self.config.rerank_threshold is not None and rerank_scores:
            candidates = [
                item
                for item in candidates
                if rerank_scores[item.chunk_id] >= self.config.rerank_threshold
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
            reranker_applied=reranker_applied,
        )
