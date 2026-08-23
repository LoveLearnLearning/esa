# backend/agent/rag/evaluation/metrics.py

"""

这个文件干什么：对固定标注集执行 Dense、两路 BM25、RRF、Reranker 分层检索评测。

直白点说就是：拿带标准答案的问题逐层打分，看召回、融合和重排到底有没有把正确 Chunk 排到前面。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True)
class EvaluationCase:
    """一个人工核对问题、正确证据集合及类别标签。"""

    case_id: str
    query: str
    answerable: bool
    relevant_chunk_ids: frozenset[str]
    relevant_evidence_ids: frozenset[str]
    target_document_ids: frozenset[str]
    category_tags: tuple[str, ...]
    annotation_note: str

    def __post_init__(self) -> None:
        """确保正例具有 Chunk/Evidence，负例不携带伪 gold。"""

        if (
            not self.case_id
            or not self.query.strip()
            or not self.annotation_note.strip()
        ):
            raise ValueError(
                "evaluation identity, query and annotation note cannot be blank"
            )
        if not self.category_tags:
            raise ValueError("evaluation cases need category tags")
        if self.answerable:
            if (
                not self.relevant_chunk_ids
                or not self.relevant_evidence_ids
                or not self.target_document_ids
            ):
                raise ValueError(
                    "answerable cases need document, chunk and evidence gold"
                )
        elif (
            self.relevant_chunk_ids
            or self.relevant_evidence_ids
            or self.target_document_ids
        ):
            raise ValueError("unanswerable cases cannot carry gold identifiers")


@dataclass(frozen=True)
class RetrievalMetrics:
    """Ranking quality plus answerability/abstention behavior for one layer."""

    query_count: int
    answerable_query_count: int
    unanswerable_query_count: int
    recall_at_20: float
    hit_at_5: float
    mrr: float
    ndcg: float
    answerable_acceptance_rate: float | None
    unanswerable_abstention_rate: float | None
    unanswerable_false_positive_rate: float | None
    answerability_accuracy: float


def _metrics(
    cases: Sequence[EvaluationCase],
    rankings: Sequence[Sequence[str]],
) -> RetrievalMetrics:
    """按问题计算指标后取宏平均，避免大文档或多答案问题主导结果。"""

    if len(cases) != len(rankings) or not cases:
        raise ValueError("cases and rankings must be non-empty and aligned")
    recalls, hits, reciprocal_ranks, ndcgs = [], [], [], []
    answerable_accepts = 0
    unanswerable_abstentions = 0
    answerable_count = sum(case.answerable for case in cases)
    unanswerable_count = len(cases) - answerable_count
    for case, ranking in zip(cases, rankings):
        accepted = bool(ranking)
        if case.answerable:
            answerable_accepts += int(accepted)
        else:
            unanswerable_abstentions += int(not accepted)
            continue
        top_20 = ranking[:20]
        recalls.append(
            len(set(top_20) & case.relevant_chunk_ids) / len(case.relevant_chunk_ids)
        )
        hits.append(float(bool(set(ranking[:5]) & case.relevant_chunk_ids)))
        positions = [
            index
            for index, chunk_id in enumerate(ranking, start=1)
            if chunk_id in case.relevant_chunk_ids
        ]
        reciprocal_ranks.append(1.0 / min(positions) if positions else 0.0)
        # 第一阶段使用二元相关性：属于标注集合记为 1，否则为 0。
        dcg = sum(
            1.0 / math.log2(index + 1)
            for index, chunk_id in enumerate(ranking[:20], start=1)
            if chunk_id in case.relevant_chunk_ids
        )
        ideal = sum(
            1.0 / math.log2(index + 1)
            for index in range(
                1,
                min(20, len(case.relevant_chunk_ids)) + 1,
            )
        )
        ndcgs.append(dcg / ideal if ideal else 0.0)
    return RetrievalMetrics(
        len(cases),
        answerable_count,
        unanswerable_count,
        mean(recalls) if recalls else 0.0,
        mean(hits) if hits else 0.0,
        mean(reciprocal_ranks) if reciprocal_ranks else 0.0,
        mean(ndcgs) if ndcgs else 0.0,
        answerable_accepts / answerable_count if answerable_count else None,
        (unanswerable_abstentions / unanswerable_count if unanswerable_count else None),
        (
            1.0 - unanswerable_abstentions / unanswerable_count
            if unanswerable_count
            else None
        ),
        (answerable_accepts + unanswerable_abstentions) / len(cases),
    )


def evaluate_layers(
    cases: Sequence[EvaluationCase],
    retrieve: Callable[[str], Mapping[str, Sequence[str]]],
) -> dict[str, RetrievalMetrics]:
    """对实际执行的检索阶段分别评分，不能伪造未执行的层。"""

    if not cases:
        raise ValueError("at least one evaluation case is required")
    traces = [retrieve(case.query) for case in cases]
    required = ("dense", "bm25_body", "bm25_heading", "fusion", "final")
    missing = [
        layer for layer in required if any(layer not in trace for trace in traces)
    ]
    if missing:
        raise ValueError(f"missing evaluation layers: {', '.join(missing)}")
    layers = [*required]
    if all("reranker" in trace for trace in traces):
        layers.insert(-1, "reranker")
    return {
        layer: _metrics(cases, [trace[layer] for trace in traces]) for layer in layers
    }
