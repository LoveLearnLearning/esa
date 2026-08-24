# backend/agent/rag/tests/test_structural_optimization.py

"""数据清洁、微批重排、跨语言查询和上下文契约的聚焦回归测试。"""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import cast

from backend.agent.DocIR.core.enums import TextOrigin
from backend.agent.rag.chunk import Chunk, ChunkEvidence, ContentRole
from backend.agent.rag.inference import HashingEmbeddingProvider
from backend.agent.rag.indexes import QdrantIndex
from backend.agent.rag.retrieval.context import (
    ContextBuilder,
    estimate_tokens,
    query_aware_excerpt,
)
from backend.agent.rag.retrieval.contracts import (
    ContextLevel,
    RankedItem,
    RetrievalConfig,
)
from backend.agent.rag.retrieval.query import RuleBasedQueryProcessor
from backend.agent.rag.retrieval.reranking import CandidateReranker
from backend.agent.rag.retrieval.routing import RouteRetriever
from backend.agent.rag.retrieval.service import RetrievalService


def _chunk(name: str, order: int, text: str | None = None) -> Chunk:
    """处理 `_chunk` 相关逻辑。"""
    body = text or name
    evidence = ChunkEvidence(
        evidence_id=f"evidence_{name}",
        element_id=f"element_{name}",
        text_layer_id=f"text_{name}",
        text_start=0,
        text_end=len(body),
        text=body,
        text_origin=TextOrigin.NATIVE_TEXT,
        quote_eligible=True,
        derivation="primary_text_span",
    )
    return Chunk(
        chunk_id=name,
        chunk_revision_id="revision",
        document_order=order,
        document_id="document",
        source_version_id="source",
        parse_revision_id="parse",
        section_id="section",
        element_ids=(f"element_{name}",),
        kind_counts={"paragraph": 1},
        content_role=ContentRole.BODY,
        dense_text=body,
        bm25_body=body,
        bm25_heading="paper > section",
        body_char_count=len(body),
        evidence=(evidence,),
    )


class _Scorer:
    """封装 `_Scorer` 的状态与行为。"""
    model_name = "recording"

    def __init__(self) -> None:
        """初始化 `_Scorer` 实例。"""
        self.batch_sizes: list[int] = []

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        """处理 `score` 相关逻辑。

        Args:
            query: str => 查询文本。
            documents: Sequence[str] => `documents` 参数。

        Returns:
            list[float] => 处理结果。
        """
        self.batch_sizes.append(len(documents))
        return [float(document.removeprefix("chunk")) for document in documents]


def test_reranker_micro_batches_all_candidates_then_sorts_globally() -> None:
    """验证 `reranker_micro_batches_all_candidates_then_sorts_globally` 场景。"""
    chunks = {f"c{i}": _chunk(f"c{i}", i, f"chunk{i}") for i in range(23)}
    fused = [RankedItem(f"c{i}", 23 - i) for i in range(23)]
    scorer = _Scorer()
    selection = CandidateReranker(
        chunks,
        scorer,
        RetrievalConfig(
            rerank_limit=23,
            reranker_batch_size=4,
            final_limit=5,
            reranker_enabled=True,
            reranker_prior_weight=0.8,
        ),
    ).select("query", fused)
    assert scorer.batch_sizes == [4, 4, 4, 4, 4, 3]
    assert len(selection.rerank_scores) == 23
    assert selection.ranking[0].chunk_id == "c22"
    assert selection.ranking[0].score == 22.0


def test_reranker_batch_size_does_not_change_score_semantics() -> None:
    """验证 `reranker_batch_size_does_not_change_score_semantics` 场景。"""
    chunks = {f"c{i}": _chunk(f"c{i}", i, f"chunk{i}") for i in range(20)}
    fused = [RankedItem(f"c{i}", 20 - i) for i in range(20)]
    rankings = []
    for batch_size in (1, 4, 8):
        rankings.append(
            CandidateReranker(
                chunks,
                _Scorer(),
                RetrievalConfig(
                    rerank_limit=20,
                    reranker_batch_size=batch_size,
                    reranker_enabled=True,
                ),
            )
            .select("query", fused)
            .ranking
        )
    assert rankings[0] == rankings[1] == rankings[2]


def test_adjacent_ranked_chunks_merge_without_losing_their_context() -> None:
    chunks = {name: _chunk(name, order) for order, name in enumerate(("A", "B", "C"))}
    chunks["X"] = _chunk("X", 10)
    selection = CandidateReranker(
        chunks,
        None,
        RetrievalConfig(final_limit=5, reranker_enabled=False),
    ).select(
        "query",
        [
            RankedItem("B", 4.0),
            RankedItem("A", 3.0),
            RankedItem("C", 2.0),
            RankedItem("X", 1.0),
        ],
    )

    assert [item.chunk_id for item in selection.final_candidates] == ["B"]
    assert selection.merged_context_chunk_ids == {"B": ("A", "C", "X")}
    plan = ContextBuilder(tuple(chunks.values()), section_window=0).plan(
        [chunks["B"]],
        ContextLevel.EVIDENCE,
        max_tokens=10,
        merged_context_chunk_ids=selection.merged_context_chunk_ids,
    )
    assert [chunk.chunk_id for chunk in plan["B"]] == ["A", "B", "C", "X"]


def test_query_aware_excerpt_keeps_answer_near_the_end() -> None:
    text = "无关背景。" * 80 + "慢启动期间拥塞窗口会指数增长。" + "附加背景。" * 20

    excerpt = query_aware_excerpt(text, "慢启动时拥塞窗口如何增长？", 24)

    assert estimate_tokens(excerpt) <= 24
    assert "拥塞窗口" in excerpt
    assert excerpt.startswith("…")
    assert excerpt.endswith("…")


class _StaticIndex:
    """封装 `_StaticIndex` 的状态与行为。"""
    configuration_fingerprint = "test"

    def dense(self, query_vector, limit, content_roles=None):
        """处理 `dense` 相关逻辑。

        Args:
            query_vector: object => `query_vector` 参数。
            limit: object => 返回数量上限。
            content_roles: object => `content_roles` 参数。

        Returns:
            object => 处理结果。
        """
        return [RankedItem("B", 3.0), RankedItem("A", 2.0), RankedItem("C", 1.0)]

    def bm25_body(self, query, limit, content_roles=None):
        """处理 `bm25_body` 相关逻辑。

        Args:
            query: object => 查询文本。
            limit: object => 返回数量上限。
            content_roles: object => `content_roles` 参数。

        Returns:
            object => 处理结果。
        """
        return self.dense([], limit, content_roles)

    def bm25_heading(self, query, limit, content_roles=None):
        """处理 `bm25_heading` 相关逻辑。

        Args:
            query: object => 查询文本。
            limit: object => 返回数量上限。
            content_roles: object => `content_roles` 参数。

        Returns:
            object => 处理结果。
        """
        return self.dense([], limit, content_roles)


def test_section_context_has_evidence_for_a_b_and_c() -> None:
    """验证 `section_context_has_evidence_for_a_b_and_c` 场景。"""
    chunks = (_chunk("A", 0), _chunk("B", 1), _chunk("C", 2))
    collection = SimpleNamespace(
        chunks=chunks, document_names={"document": "paper.pdf"}
    )
    service = RetrievalService(
        cast(object, collection),
        cast(object, _StaticIndex()),
        HashingEmbeddingProvider(),
        None,
        RetrievalConfig(final_limit=1, section_window=1),
    )
    hit = service.search("query", ContextLevel.SECTION).hits[0]
    assert hit.context_chunk_ids == ("A", "B", "C")
    assert tuple(item.chunk_id for item in hit.evidence) == ("B", "A", "C")
    assert hit.context_text == "A\n\nB\n\nC"


def test_full_read_evidence_covers_every_context_chunk() -> None:
    """验证 `full_read_evidence_covers_every_context_chunk` 场景。"""
    chunks = (_chunk("A", 0), _chunk("B", 1), _chunk("C", 2))
    collection = SimpleNamespace(
        chunks=chunks, document_names={"document": "paper.pdf"}
    )
    service = RetrievalService(
        cast(object, collection),
        cast(object, _StaticIndex()),
        HashingEmbeddingProvider(),
        None,
        RetrievalConfig(final_limit=1),
    )
    hit = service.search("query", ContextLevel.FULL_READ).hits[0]
    assert set(hit.context_chunk_ids) == {item.chunk_id for item in hit.evidence}


def test_context_budget_prioritizes_primary_hits_and_deduplicates() -> None:
    """验证 `context_budget_prioritizes_primary_hits_and_deduplicates` 场景。"""
    chunks = [_chunk("A", 0), _chunk("B", 1), _chunk("C", 2)]
    plan = ContextBuilder(chunks, section_window=1).plan(
        [chunks[1], chunks[2]], ContextLevel.SECTION, max_tokens=3
    )
    flattened = [chunk for parts in plan.values() for chunk in parts]
    assert {chunk.chunk_id for chunk in flattened} == {"B", "C"}
    assert len(flattened) == len({chunk.chunk_id for chunk in flattened})
    assert sum(estimate_tokens(chunk.bm25_body) for chunk in flattened) + 1 <= 3


class _RecordingEmbedding:
    """封装 `_RecordingEmbedding` 的状态与行为。"""
    model_name = "recording"

    def __init__(self) -> None:
        """初始化 `_RecordingEmbedding` 实例。"""
        self.query = ""

    def embed(self, texts):
        """处理 `embed` 相关逻辑。"""
        self.query = texts[0]
        return [[1.0]]


class _RecordingIndex:
    """封装 `_RecordingIndex` 的状态与行为。"""
    def __init__(self) -> None:
        """初始化 `_RecordingIndex` 实例。"""
        self.body_query = ""
        self.heading_query = ""

    def dense(self, query_vector, limit, content_roles=None):
        """处理 `dense` 相关逻辑。

        Args:
            query_vector: object => `query_vector` 参数。
            limit: object => 返回数量上限。
            content_roles: object => `content_roles` 参数。

        Returns:
            object => 处理结果。
        """
        return []

    def bm25_body(self, query, limit, content_roles=None):
        """处理 `bm25_body` 相关逻辑。

        Args:
            query: object => 查询文本。
            limit: object => 返回数量上限。
            content_roles: object => `content_roles` 参数。

        Returns:
            object => 处理结果。
        """
        self.body_query = query
        return []

    def bm25_heading(self, query, limit, content_roles=None):
        """处理 `bm25_heading` 相关逻辑。

        Args:
            query: object => 查询文本。
            limit: object => 返回数量上限。
            content_roles: object => `content_roles` 参数。

        Returns:
            object => 处理结果。
        """
        self.heading_query = query
        return []


def test_chinese_query_expands_bm25_but_dense_keeps_original() -> None:
    """验证 `chinese_query_expands_bm25_but_dense_keeps_original` 场景。"""
    query = "BKT 中猜测概率是什么意思？"
    processor = RuleBasedQueryProcessor()
    variants = processor.process(query)
    assert "guess probability" in variants.expansions
    assert "Bayesian Knowledge Tracing" in variants.expansions
    index = _RecordingIndex()
    embedding = _RecordingEmbedding()
    RouteRetriever(
        cast(object, index), cast(object, embedding), RetrievalConfig()
    ).retrieve(query)
    assert embedding.query == query
    assert query in index.body_query and "guess probability" in index.body_query
    assert "guess probability" in index.heading_query


def test_query_processor_failure_falls_back_to_original() -> None:
    """验证 `query_processor_failure_falls_back_to_original` 场景。"""
    class FailingProcessor:
        """封装 `FailingProcessor` 的状态与行为。"""
        def process(self, query: str):
            """处理 `process` 相关数据。"""
            raise RuntimeError("offline")

    index = _RecordingIndex()
    embedding = _RecordingEmbedding()
    result = RouteRetriever(
        cast(object, index),
        cast(object, embedding),
        RetrievalConfig(),
        cast(object, FailingProcessor()),
    ).retrieve("original query")
    assert index.body_query == index.heading_query == "original query"
    assert result.degraded == ("query_processor_fallback:RuntimeError",)


def test_reference_intent_opens_suppressed_roles() -> None:
    """验证 `reference_intent_opens_suppressed_roles` 场景。"""
    variants = RuleBasedQueryProcessor().process("这篇论文引用了哪些研究？")
    assert ContentRole.REFERENCE in variants.content_roles
    assert ContentRole.METADATA not in variants.content_roles


def test_author_intent_opens_author_and_affiliation_roles() -> None:
    """验证 `author_intent_opens_author_and_affiliation_roles` 场景。"""
    variants = RuleBasedQueryProcessor().process("这篇论文的作者和所属机构是什么？")
    assert {ContentRole.AUTHOR_INFO, ContentRole.AFFILIATION} <= variants.content_roles


class _CapturingQdrant(QdrantIndex):
    """封装 `_CapturingQdrant` 的状态与行为。"""
    def __init__(self) -> None:
        """初始化 `_CapturingQdrant` 实例。"""
        super().__init__("http://127.0.0.1:6333", "test")
        self.payload = None

    def _request(self, method, path, payload=None):
        """处理 `_request` 相关逻辑。"""
        self.payload = payload
        return {"result": {"points": []}}


def test_qdrant_queries_filter_by_content_role() -> None:
    """验证 `qdrant_queries_filter_by_content_role` 场景。"""
    index = _CapturingQdrant()
    index.bm25_body("query", 5, frozenset({ContentRole.BODY, ContentRole.TABLE}))
    assert index.payload["with_payload"] == {"include": ["chunk_id"]}
    assert index.payload["filter"]["must"][0] == {
        "key": "content_role",
        "match": {"any": ["body", "table"]},
    }
