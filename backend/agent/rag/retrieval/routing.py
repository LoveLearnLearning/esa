# backend/agent/rag/retrieval/routing.py

"""

这个文件干什么：封装 Dense、BM25 Body、BM25 Heading 三路独立召回及 Dense 降级。

直白点说就是：同时走语义、正文关键词和标题关键词三条路找候选；语义路线坏了还能保留关键词检索。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..indexes import IndexUnavailable
from ..inference import InferenceUnavailable
from .contracts import (
    EmbeddingProvider,
    RankedItem,
    RetrievalConfig,
    RetrievalIndex,
)


@dataclass(frozen=True)
class RouteResult:
    """一次查询的三路排名和召回阶段降级记录。"""

    routes: Mapping[str, list[RankedItem]]
    degraded: tuple[str, ...]


@dataclass(frozen=True)
class RouteRetriever:
    """执行三路独立召回，不负责融合、重排或证据组装。"""

    index: RetrievalIndex
    embedding: EmbeddingProvider
    config: RetrievalConfig

    def retrieve(self, query: str) -> RouteResult:
        """返回 Dense、正文 BM25、标题 BM25 排名及可观测降级原因。"""

        degraded: list[str] = []
        routes: dict[str, list[RankedItem]] = {}

        try:
            embed_query = getattr(self.embedding, "embed_query", None)
            query_vector = (
                embed_query(query)
                if embed_query
                else self.embedding.embed([query])[0]
            )
            routes["dense"] = self.index.dense(
                query_vector,
                self.config.dense_limit,
            )
        except (InferenceUnavailable, IndexUnavailable, IndexError) as exc:
            degraded.append(f"dense_unavailable:{type(exc).__name__}")
            routes["dense"] = []

        routes["bm25_body"] = self.index.bm25_body(
            query,
            self.config.bm25_body_limit,
        )
        routes["bm25_heading"] = self.index.bm25_heading(
            query,
            self.config.bm25_heading_limit,
        )
        return RouteResult(routes, tuple(degraded))
