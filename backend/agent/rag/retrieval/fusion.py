# backend/agent/rag/retrieval/fusion.py

"""

这个文件干什么：实现与原始分数量纲无关的排名融合，以及重排后的重叠 Chunk 合并。

直白点说就是：把三路召回名次合成一个总排名，再去掉同一重叠组里重复占位的 Chunk。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from ..chunk import Chunk
from .contracts import RankedItem


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
