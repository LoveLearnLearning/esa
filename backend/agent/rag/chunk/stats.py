# backend/agent/rag/chunk/stats.py

"""

这个文件干什么：ChunkDocument 与 ChunkCollection 的确定性统计。

直白点说就是：统计一批 Chunk 有多少、长度怎样分布、各种内容类型各占多少。

ChunkDocument 与 ChunkCollection 的确定性统计。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import TypedDict

from .models import ChunkDocument


class ChunkLengthStats(TypedDict):
    """Chunk 正文长度分布。"""

    min: int
    p50: int
    p90: int
    p95: int
    max: int


class CollectionStats(TypedDict):
    """ChunkCollection 的确定性统计结构。"""

    documents: int
    chunks: int
    characters: int
    chunk_length: ChunkLengthStats
    kind_occurrences: dict[str, int]
    evidence_origins: dict[str, int]
    element_dispositions: dict[str, int]
    exclusion_reasons: dict[str, int]
    table_chunks: int
    multi_page_evidence: int


def _percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * ratio))]


def collection_stats(documents: Iterable[ChunkDocument]) -> CollectionStats:
    docs = list(documents)
    lengths = [chunk.body_char_count for document in docs for chunk in document.chunks]
    kinds: Counter[str] = Counter()
    origins: Counter[str] = Counter()
    dispositions: Counter[str] = Counter()
    exclusion_reasons: Counter[str] = Counter()
    multi_page = 0
    table_chunks = 0
    for document in docs:
        for chunk in document.chunks:
            kinds.update(chunk.kind_counts)
            table_chunks += int("table" in chunk.kind_counts)
            for evidence in chunk.evidence:
                origins[evidence.text_origin.value] += 1
                multi_page += int(len(evidence.page_ids) > 1)
        for item in document.element_dispositions:
            dispositions[item.action] += 1
            if item.action == "excluded":
                exclusion_reasons[item.reason] += 1
    return {
        "documents": len(docs),
        "chunks": sum(len(document.chunks) for document in docs),
        "characters": sum(lengths),
        "chunk_length": {
            "min": min(lengths, default=0),
            "p50": _percentile(lengths, 0.50),
            "p90": _percentile(lengths, 0.90),
            "p95": _percentile(lengths, 0.95),
            "max": max(lengths, default=0),
        },
        "kind_occurrences": dict(sorted(kinds.items())),
        "evidence_origins": dict(sorted(origins.items())),
        "element_dispositions": dict(sorted(dispositions.items())),
        "exclusion_reasons": dict(sorted(exclusion_reasons.items())),
        "table_chunks": table_chunks,
        "multi_page_evidence": multi_page,
    }
