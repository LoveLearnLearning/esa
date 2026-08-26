# backend/agent/rag/retrieval/routing.py

"""

这个文件干什么：按配置执行 Dense，以及显式实验启用的 BM25 召回。

直白点说就是：默认只走语义检索；只有明确选择词法融合实验时才查询 BM25。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ..indexes import IndexUnavailable
from ..inference import InferenceUnavailable
from .contracts import (
    EmbeddingProvider,
    RankedItem,
    RetrievalConfig,
    RetrievalIndex,
)
from .query import QueryProcessor, QueryVariants, RuleBasedQueryProcessor


@dataclass(frozen=True)
class RouteResult:
    """一次查询的各路排名和召回阶段降级记录。"""

    routes: Mapping[str, list[RankedItem]]
    degraded: tuple[str, ...]


@dataclass(frozen=True)
class RouteRetriever:
    """执行配置允许的召回路线，不负责融合、重排或证据组装。"""

    index: RetrievalIndex
    embedding: EmbeddingProvider
    config: RetrievalConfig
    query_processor: QueryProcessor = field(default_factory=RuleBasedQueryProcessor)

    def retrieve(self, query: str) -> RouteResult:
        """返回 Dense 和显式启用的 BM25 排名及可观测降级原因。"""

        degraded: list[str] = []
        routes: dict[str, list[RankedItem]] = {}

        try:
            variants = self.query_processor.process(query)
        except Exception as exc:  # query rewrite is deliberately fail-open
            degraded.append(f"query_processor_fallback:{type(exc).__name__}")
            variants = QueryVariants(query)

        try:
            embed_query = getattr(self.embedding, "embed_query", None)
            query_vector = (
                embed_query(query) if embed_query else self.embedding.embed([query])[0]
            )
            routes["dense"] = self.index.dense(
                query_vector,
                self.config.dense_limit,
                variants.content_roles,
            )
        except (InferenceUnavailable, IndexUnavailable, IndexError) as exc:
            degraded.append(f"dense_unavailable:{type(exc).__name__}")
            routes["dense"] = []

        if self.config.fusion_method == "dense":
            routes["bm25_body"] = []
            routes["bm25_heading"] = []
            return RouteResult(routes, tuple(degraded))

        routes["bm25_body"] = self.index.bm25_body(
            variants.bm25_body_query,
            self.config.bm25_body_limit,
            variants.content_roles,
        )
        routes["bm25_heading"] = self.index.bm25_heading(
            variants.bm25_heading_query,
            self.config.bm25_heading_limit,
            variants.content_roles,
        )
        return RouteResult(routes, tuple(degraded))
