# backend/agent/rag/retrieval/reranking.py

"""

这个文件干什么：封装 RRF 候选的模型重排、阈值筛选和显式重叠 Chunk 去重。

直白点说就是：让模型重新判断候选相关性并筛选结果；模型出故障时就稳妥地沿用原来的融合顺序。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..chunk import Chunk
from ..inference import InferenceUnavailable
from .contracts import RankedItem, Reranker, RetrievalConfig
from .fusion import consolidate_overlaps


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

        if self.reranker is not None and candidates:
            try:
                documents = [
                    self.chunks[item.chunk_id].dense_text
                    for item in candidates
                ]
                scores = self.reranker.score(query, documents)
                if len(scores) != len(candidates):
                    raise ValueError(
                        "reranker output count does not match candidates"
                    )
                rerank_scores = {
                    item.chunk_id: score
                    for item, score in zip(candidates, scores)
                }
                candidates = [
                    RankedItem(item.chunk_id, rerank_scores[item.chunk_id])
                    for item in candidates
                ]
                candidates.sort(key=lambda item: (-item.score, item.chunk_id))
            except InferenceUnavailable as exc:
                degraded.append(
                    f"reranker_unavailable:{type(exc).__name__}"
                )
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
            consolidate_overlaps(candidates, self.chunks)[
                : self.config.final_limit
            ]
        )
        return CandidateSelection(
            ranking=ranking,
            final_candidates=final_candidates,
            rerank_scores=rerank_scores,
            degraded=tuple(degraded),
        )
