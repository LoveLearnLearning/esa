# backend/agent/rag/retrieval/reranking.py

"""

这个文件干什么：封装 fusion 候选的模型重排、阈值筛选和显式重叠 Chunk 去重。

直白点说就是：让模型重新判断候选相关性并筛选结果；模型出故障时就稳妥地沿用原来的融合顺序。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math

from backend.agent.DocIR.core.geometry import Locator

from ..chunk import Chunk, ChunkEvidence
from ..inference import InferenceUnavailable
from .contracts import RankedItem, Reranker, RetrievalConfig


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

    preselection: tuple[RankedItem, ...]
    ranking: tuple[RankedItem, ...]
    final_candidates: tuple[RankedItem, ...]
    rerank_scores: Mapping[str, float]
    merged_context_chunk_ids: Mapping[str, tuple[str, ...]]
    degraded: tuple[str, ...]
    reranker_applied: bool


def consolidate_overlapping_candidates(
    ranked: Sequence[RankedItem],
    chunks: Mapping[str, Chunk],
) -> tuple[list[RankedItem], dict[str, tuple[str, ...]]]:
    """Keep one ranked hit per explicitly or geometrically overlapping region."""

    accepted: list[RankedItem] = []
    seen: list[Chunk] = []
    owners_by_chunk_id: dict[str, str] = {}
    merged: dict[str, list[str]] = {}
    group_owners: dict[tuple[str, str, str], str] = {}
    for item in ranked:
        chunk = chunks[item.chunk_id]
        owner_id = next(
            (
                group_owners[(chunk.document_id, chunk.section_id, group)]
                for group in chunk.overlap_group_ids
                if (chunk.document_id, chunk.section_id, group) in group_owners
            ),
            None,
        )
        if owner_id is None:
            for previous in seen:
                if _same_result_region(previous, chunk):
                    owner_id = owners_by_chunk_id[previous.chunk_id]
                    break
        if owner_id is not None:
            merged.setdefault(owner_id, []).append(chunk.chunk_id)
            owners_by_chunk_id[chunk.chunk_id] = owner_id
            seen.append(chunk)
            for group in chunk.overlap_group_ids:
                group_owners.setdefault(
                    (chunk.document_id, chunk.section_id, group),
                    owner_id,
                )
            continue
        accepted.append(item)
        merged.setdefault(chunk.chunk_id, [])
        owners_by_chunk_id[chunk.chunk_id] = chunk.chunk_id
        seen.append(chunk)
        for group in chunk.overlap_group_ids:
            group_owners.setdefault(
                (chunk.document_id, chunk.section_id, group),
                chunk.chunk_id,
            )

    return accepted, {
        owner: tuple(
            sorted(values, key=lambda chunk_id: chunks[chunk_id].document_order)
        )
        for owner, values in merged.items()
    }


def _same_result_region(
    left: Chunk,
    right: Chunk,
) -> bool:
    if left.document_id != right.document_id:
        return False
    if left.section_id != right.section_id:
        return False
    return _evidence_regions_overlap(left, right)


def _evidence_regions_overlap(left: Chunk, right: Chunk) -> bool:
    """Require real text-span or page-geometry overlap; sharing a page is insufficient."""

    for left_evidence in left.evidence:
        for right_evidence in right.evidence:
            if _text_spans_overlap(left_evidence, right_evidence):
                return True
            for left_locator in left_evidence.locators:
                for right_locator in right_evidence.locators:
                    if _locators_overlap(left_locator, right_locator):
                        return True
    return False


def _text_spans_overlap(left: ChunkEvidence, right: ChunkEvidence) -> bool:
    left_start = left.text_start
    left_end = left.text_end
    right_start = right.text_start
    right_end = right.text_end
    return bool(
        left.element_id == right.element_id
        and left.text_layer_id == right.text_layer_id
        and left_start is not None
        and left_end is not None
        and right_start is not None
        and right_end is not None
        and left_start < right_end
        and right_start < left_end
    )


def _locators_overlap(left: Locator, right: Locator) -> bool:
    left_bbox = left.bbox
    right_bbox = right.bbox
    if left_bbox is None or right_bbox is None:
        return False
    left_page = _locator_page_key(left)
    if left_page is None or left_page != _locator_page_key(right):
        return False
    return bool(
        left_bbox.x0 < right_bbox.x1
        and right_bbox.x0 < left_bbox.x1
        and left_bbox.y0 < right_bbox.y1
        and right_bbox.y0 < left_bbox.y1
    )


def _locator_page_key(locator: Locator) -> tuple[str, object] | None:
    if locator.page_id is not None:
        return ("page_id", locator.page_id)
    if locator.page is not None:
        return ("page", locator.page)
    if locator.container_id is not None and locator.container_index is not None:
        return ("container", (locator.container_id, locator.container_index))
    return None


def diversify_rerank_candidates(
    ranked: Sequence[RankedItem],
    chunks: Mapping[str, Chunk],
    limit: int,
) -> list[RankedItem]:
    """Preserve a relevance core while preventing one document/section dominating."""

    document_cap = max(2, math.ceil(limit * 0.4))
    return _select_with_soft_caps(
        ranked,
        chunks,
        limit,
        passes=(
            (2, document_cap),
            (None, document_cap),
            (None, None),
        ),
    )


def diversify_final_candidates(
    ranked: Sequence[RankedItem],
    chunks: Mapping[str, Chunk],
    limit: int,
) -> list[RankedItem]:
    """Build a diverse Top-K, then relax caps to guarantee deterministic refill."""

    document_cap = max(1, math.ceil(limit * 0.6))
    return _select_with_soft_caps(
        ranked,
        chunks,
        limit,
        passes=(
            (1, document_cap),
            (2, limit),
            (None, None),
        ),
    )


def _select_with_soft_caps(
    ranked: Sequence[RankedItem],
    chunks: Mapping[str, Chunk],
    limit: int,
    *,
    passes: Sequence[tuple[int | None, int | None]],
) -> list[RankedItem]:
    accepted: list[RankedItem] = []
    accepted_ids: set[str] = set()
    document_counts: dict[str, int] = {}
    section_counts: dict[tuple[str, str], int] = {}
    for section_cap, document_cap in passes:
        for item in ranked:
            if item.chunk_id in accepted_ids:
                continue
            chunk = chunks[item.chunk_id]
            section_key = (chunk.document_id, chunk.section_id)
            if (
                document_cap is not None
                and document_counts.get(chunk.document_id, 0) >= document_cap
            ):
                continue
            if (
                section_cap is not None
                and section_counts.get(section_key, 0) >= section_cap
            ):
                continue
            accepted.append(item)
            accepted_ids.add(item.chunk_id)
            document_counts[chunk.document_id] = (
                document_counts.get(chunk.document_id, 0) + 1
            )
            section_counts[section_key] = section_counts.get(section_key, 0) + 1
            if len(accepted) == limit:
                return accepted
    return accepted


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

        overlap_deduplicated, overlap_merged = consolidate_overlapping_candidates(
            fused,
            self.chunks,
        )
        candidates = diversify_rerank_candidates(
            overlap_deduplicated,
            self.chunks,
            self.config.rerank_limit,
        )
        preselection = tuple(candidates)
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
            diversify_final_candidates(
                candidates,
                self.chunks,
                self.config.final_limit,
            )
        )
        return CandidateSelection(
            preselection=preselection,
            ranking=ranking,
            final_candidates=final_candidates,
            rerank_scores=rerank_scores,
            merged_context_chunk_ids={
                item.chunk_id: overlap_merged.get(item.chunk_id, ())
                for item in final_candidates
            },
            degraded=tuple(degraded),
            reranker_applied=reranker_applied,
        )
