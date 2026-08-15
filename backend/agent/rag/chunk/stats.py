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

SHORT_CHUNK_AUDIT_THRESHOLD = 120


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
    content_roles: dict[str, int]
    default_filtered_chunks: int
    table_chunks: int
    multi_locator_evidence: int


def _percentile(values: list[int], ratio: float) -> int:
    """处理 `_percentile` 相关逻辑。"""
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * ratio))]


def collection_stats(documents: Iterable[ChunkDocument]) -> CollectionStats:
    """处理 `collection_stats` 相关逻辑。

    Args:
        documents: Iterable[ChunkDocument] => `documents` 参数。

    Returns:
        CollectionStats => 处理结果。
    """
    docs = list(documents)
    lengths = [chunk.body_char_count for document in docs for chunk in document.chunks]
    kinds: Counter[str] = Counter()
    origins: Counter[str] = Counter()
    dispositions: Counter[str] = Counter()
    exclusion_reasons: Counter[str] = Counter()
    content_roles: Counter[str] = Counter()
    default_filtered_chunks = 0
    multi_locator = 0
    table_chunks = 0
    for document in docs:
        for chunk in document.chunks:
            kinds.update(chunk.kind_counts)
            content_roles[chunk.content_role.value] += 1
            default_filtered_chunks += int(not chunk.retrieval_enabled)
            table_chunks += int("table" in chunk.kind_counts)
            for evidence in chunk.evidence:
                origins[evidence.text_origin.value] += 1
                multi_locator += int(len(evidence.locators) > 1)
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
        "content_roles": dict(sorted(content_roles.items())),
        "default_filtered_chunks": default_filtered_chunks,
        "table_chunks": table_chunks,
        "multi_locator_evidence": multi_locator,
    }


def short_chunk_audit(
    documents: Iterable[ChunkDocument],
    *,
    threshold: int = SHORT_CHUNK_AUDIT_THRESHOLD,
) -> dict:
    """逐条解释低于固定治理阈值的 Chunk 为何仍被保留。"""

    if threshold <= 0:
        raise ValueError("short chunk audit threshold 必须为正")
    entries: list[dict] = []
    for document in documents:
        chunks = document.chunks
        for index, chunk in enumerate(chunks):
            if chunk.body_char_count >= threshold:
                continue
            special_kinds = sorted(
                set(chunk.kind_counts).intersection({"table", "formula", "code", "figure"})
            )
            if special_kinds:
                reason = "special_element_boundary"
            elif (
                len(chunk.element_ids) == 1
                and len(chunk.evidence) == 1
                and "\n" not in chunk.bm25_body
                and not chunk.bm25_body.rstrip().endswith(
                    ("。", "！", "？", ".", "!", "?", ";", "；")
                )
            ):
                reason = "meaningful_short_element"
            else:
                reason = "no_safe_same_section_neighbor"
            entries.append(
                {
                    "document_id": document.document_id,
                    "filename": document.filename,
                    "chunk_id": chunk.chunk_id,
                    "document_order": chunk.document_order,
                    "section_id": chunk.section_id,
                    "section_path": list(chunk.section_path),
                    "content_role": chunk.content_role.value,
                    "body_char_count": chunk.body_char_count,
                    "element_ids": list(chunk.element_ids),
                    "kind_counts": chunk.kind_counts,
                    "retention_reason": reason,
                    "special_kinds": special_kinds,
                }
            )
    entries.sort(key=lambda item: (item["document_id"], item["document_order"]))
    reason_counts = Counter(item["retention_reason"] for item in entries)
    return {
        "schema_name": "short_chunk_audit",
        "schema_version": "0.1",
        "threshold_exclusive": threshold,
        "short_chunk_count": len(entries),
        "retention_reasons": dict(sorted(reason_counts.items())),
        "chunks": entries,
    }
