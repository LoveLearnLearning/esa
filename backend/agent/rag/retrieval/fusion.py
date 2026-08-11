# backend/agent/rag/retrieval/fusion.py

"""

这个文件干什么：实现与原始分数量纲无关的排名融合，以及重排后的重叠 Chunk 合并。

直白点说就是：把三路召回名次合成一个总排名，再去掉同一重叠组里重复占位的 Chunk。
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..chunk import Chunk
from .calibration import ScoreCalibrator
from .contracts import RankedItem


@dataclass(frozen=True)
class FusionCandidate:
    """一个 union candidate 的原始分数、路由名次和最终融合分数。"""

    chunk_id: str
    dense_raw_score: float | None
    bm25_body_raw_score: float | None
    bm25_heading_raw_score: float | None
    dense_rank: int | None
    bm25_body_rank: int | None
    bm25_heading_rank: int | None
    dense_calibrated_score: float
    bm25_body_calibrated_score: float
    bm25_heading_calibrated_score: float
    lexical_score: float
    final_score: float


@dataclass(frozen=True)
class FusionResult:
    """可直接排序的结果及可离线审计的逐候选分数。"""

    ranking: tuple[RankedItem, ...]
    candidates: tuple[FusionCandidate, ...]
    lexical_confidence: float


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[RankedItem]],
    *,
    rrf_k: int = 60,
    limit: int | None = None,
) -> list[RankedItem]:
    """只根据名次计算 RRF，不混用 Dense、BM25 的原始分数量纲。"""

    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    scores: dict[str, float] = defaultdict(float)
    best_rank: dict[str, int] = {}
    # 固定遍历顺序和最终平分裁决规则，保证同一输入得到完全相同的输出。
    for route in sorted(rankings):
        seen: set[str] = set()
        for rank, item in enumerate(rankings[route], start=1):
            if item.chunk_id in seen:
                continue
            seen.add(item.chunk_id)
            scores[item.chunk_id] += 1.0 / (rrf_k + rank)
            best_rank[item.chunk_id] = min(best_rank.get(item.chunk_id, rank), rank)
    fused = [RankedItem(chunk_id, score) for chunk_id, score in scores.items()]
    fused.sort(key=lambda item: (-item.score, best_rank[item.chunk_id], item.chunk_id))
    return fused[:limit] if limit is not None else fused


def weighted_reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[RankedItem]],
    weights: Mapping[str, float],
    *,
    rrf_k: int = 60,
    limit: int | None = None,
) -> list[RankedItem]:
    """使用显式路由权重的 RRF；权重为零的路由不进入候选集合。"""

    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    if any(not math.isfinite(value) or value < 0 for value in weights.values()):
        raise ValueError("RRF weights must be finite and non-negative")
    scores: dict[str, float] = defaultdict(float)
    best_rank: dict[str, int] = {}
    for route in sorted(rankings):
        weight = float(weights.get(route, 0.0))
        if weight == 0:
            continue
        seen: set[str] = set()
        for rank, item in enumerate(rankings[route], start=1):
            if item.chunk_id in seen:
                continue
            seen.add(item.chunk_id)
            scores[item.chunk_id] += weight / (rrf_k + rank)
            best_rank[item.chunk_id] = min(best_rank.get(item.chunk_id, rank), rank)
    fused = [RankedItem(chunk_id, score) for chunk_id, score in scores.items()]
    fused.sort(key=lambda item: (-item.score, best_rank[item.chunk_id], item.chunk_id))
    return fused[:limit] if limit is not None else fused


_EXACT_REFERENCE = re.compile(
    r"(?iu)(?:\bRFC\s*\d+\b|\b(?:figure|fig\.?|section|sec\.?)\s*\d+(?:\.\d+)*\b)"
)
_VERSION = re.compile(r"(?iu)(?:\bv?\d+(?:\.\d+){1,3}\b|\b\d{4}\b)")
_ACRONYM = re.compile(r"(?<!\w)[A-Z][A-Z0-9-]{1,9}(?!\w)")
_PROPER_NAME = re.compile(r"(?<!\w)[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+(?!\w)")
_SPECIAL = re.compile(r"[-_/#§:]|[A-Za-z]+\.\d+")


def lexical_confidence(
    query: str,
    bm25_results: Sequence[RankedItem],
    calibrator: ScoreCalibrator,
) -> float:
    """估计词法路线是否值得补漏；使用绝对校准分数而非 query 内 min-max。"""

    if not bm25_results:
        return 0.0
    signal = 0.05
    signal += 0.35 if _EXACT_REFERENCE.search(query) else 0.0
    signal += 0.20 if _VERSION.search(query) else 0.0
    signal += 0.25 if _ACRONYM.search(query) else 0.0
    signal += 0.15 if _PROPER_NAME.search(query) else 0.0
    signal += 0.10 if _SPECIAL.search(query) else 0.0
    signal = min(1.0, signal)

    top = float(bm25_results[0].score)
    absolute = calibrator.calibrate(top)
    second = float(bm25_results[1].score) if len(bm25_results) > 1 else 0.0
    margin = max(0.0, top - second) / max(abs(top), 1e-12)
    confidence = 0.55 * signal + 0.30 * absolute + 0.15 * min(1.0, margin)
    return min(1.0, max(0.0, confidence))


def score_level_weighted_fusion(
    rankings: Mapping[str, Sequence[RankedItem]],
    calibrators: Mapping[str, ScoreCalibrator],
    *,
    query: str,
    alpha: float,
    beta: float,
    limit: int | None = None,
    lexical_gate: float | None = None,
) -> FusionResult:
    """在三路候选 union 上执行经过校准、Dense 主导的 score-level fusion。"""

    if not 0 <= alpha <= 1 or not 0 <= beta <= 1:
        raise ValueError("fusion weights must be between zero and one")
    required = {"dense", "bm25_body", "bm25_heading"}
    if missing := required - set(calibrators):
        raise ValueError(f"missing score calibrators: {sorted(missing)}")

    route_values = {name: tuple(rankings.get(name, ())) for name in required}
    if alpha == 1.0:
        dense = route_values["dense"]
        dense_ranking = tuple(dense[:limit] if limit is not None else dense)
    else:
        dense_ranking = ()

    raw: dict[str, dict[str, float]] = defaultdict(dict)
    ranks: dict[str, dict[str, int]] = defaultdict(dict)
    for route, items in route_values.items():
        seen: set[str] = set()
        for rank, item in enumerate(items, 1):
            if item.chunk_id in seen:
                continue
            seen.add(item.chunk_id)
            if not math.isfinite(item.score):
                raise ValueError(f"non-finite score from route {route}")
            raw[item.chunk_id][route] = float(item.score)
            ranks[item.chunk_id][route] = rank

    gate = (
        max(
            lexical_confidence(
                query, route_values["bm25_body"], calibrators["bm25_body"]
            ),
            lexical_confidence(
                query,
                route_values["bm25_heading"],
                calibrators["bm25_heading"],
            ),
        )
        if lexical_gate is None
        else float(lexical_gate)
    )
    if not math.isfinite(gate) or not 0 <= gate <= 1:
        raise ValueError("lexical_gate must be finite and between zero and one")

    diagnostics: list[FusionCandidate] = []
    best_rank: dict[str, int] = {}
    for chunk_id in sorted(raw):
        values = raw[chunk_id]
        route_ranks = ranks[chunk_id]
        dense = (
            calibrators["dense"].calibrate(values["dense"])
            if "dense" in values
            else 0.0
        )
        body = (
            calibrators["bm25_body"].calibrate(values["bm25_body"])
            if "bm25_body" in values
            else 0.0
        )
        heading = (
            calibrators["bm25_heading"].calibrate(values["bm25_heading"])
            if "bm25_heading" in values
            else 0.0
        )
        lexical = beta * body + (1.0 - beta) * heading
        final = alpha * dense + (1.0 - alpha) * gate * lexical
        best_rank[chunk_id] = min(route_ranks.values())
        diagnostics.append(
            FusionCandidate(
                chunk_id=chunk_id,
                dense_raw_score=values.get("dense"),
                bm25_body_raw_score=values.get("bm25_body"),
                bm25_heading_raw_score=values.get("bm25_heading"),
                dense_rank=route_ranks.get("dense"),
                bm25_body_rank=route_ranks.get("bm25_body"),
                bm25_heading_rank=route_ranks.get("bm25_heading"),
                dense_calibrated_score=dense,
                bm25_body_calibrated_score=body,
                bm25_heading_calibrated_score=heading,
                lexical_score=lexical,
                final_score=final,
            )
        )
    diagnostics.sort(
        key=lambda item: (-item.final_score, best_rank[item.chunk_id], item.chunk_id)
    )
    ranking = (
        dense_ranking
        if alpha == 1.0
        else tuple(RankedItem(item.chunk_id, item.final_score) for item in diagnostics)
    )
    if limit is not None and alpha != 1.0:
        ranking = ranking[:limit]
    return FusionResult(ranking, tuple(diagnostics), gate)


def consolidate_overlaps(
    ranked: Sequence[RankedItem], chunks: Mapping[str, Chunk]
) -> list[RankedItem]:
    """按当前排名顺序，每个显式重叠组只保留最靠前的 Chunk。"""
    accepted: list[RankedItem] = []
    occupied_groups: set[str] = set()
    for item in ranked:
        groups = set(chunks[item.chunk_id].overlap_group_ids)
        if groups and groups & occupied_groups:
            continue
        accepted.append(item)
        occupied_groups.update(groups)
    return accepted
