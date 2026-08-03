# backend/agent/rag/retrieval/service.py

"""

这个文件干什么：作为第一阶段核心检索链的薄编排层，协调召回、融合、重排和证据输出。

直白点说就是：像总调度员一样按顺序叫召回、融合、重排和证据模块干活，自己只负责把流程串起来。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ..chunk import Chunk
from ..collection import LoadedChunkCollection
from .context import ContextBuilder, EvidenceAssembler
from .contracts import (
    ContextLevel,
    EmbeddingProvider,
    RankedItem,
    Reranker,
    RetrievalConfig,
    RetrievalIndex,
    SearchHit,
    SearchResponse,
    SearchTrace,
)
from .fusion import reciprocal_rank_fusion
from .reranking import CandidateReranker, CandidateSelection
from .routing import RouteRetriever


@dataclass
class RetrievalService:
    """通过多个单一职责组件编排第一阶段检索流程。"""

    collection: LoadedChunkCollection
    index: RetrievalIndex
    embedding: EmbeddingProvider
    reranker: Reranker | None
    config: RetrievalConfig = field(default_factory=RetrievalConfig)

    def __post_init__(self) -> None:
        """建立 Chunk 映射，并初始化召回、重排和上下文组件。"""

        self._chunks = {
            chunk.chunk_id: chunk
            for chunk in self.collection.chunks
        }
        self._route_retriever = RouteRetriever(
            self.index,
            self.embedding,
            self.config,
        )
        self._candidate_reranker = CandidateReranker(
            self._chunks,
            self.reranker,
            self.config,
        )
        self._context_builder = ContextBuilder(
            self.collection.chunks,
            self.config.section_window,
        )

    def _build_hit(
        self,
        item: RankedItem,
        context_level: ContextLevel,
        fused_scores: Mapping[str, float],
        selection: CandidateSelection,
    ) -> SearchHit:
        """把最终候选转换为包含引用与章节上下文的 SearchHit。"""

        chunk: Chunk = self._chunks[item.chunk_id]
        context = self._context_builder.select(chunk, context_level)
        return SearchHit(
            chunk_id=chunk.chunk_id,
            rrf_score=fused_scores[chunk.chunk_id],
            rerank_score=selection.rerank_scores.get(chunk.chunk_id),
            evidence=EvidenceAssembler.build(
                chunk,
                self.collection.document_names[chunk.document_id],
            ),
            context_chunk_ids=tuple(part.chunk_id for part in context),
            context_text="\n\n".join(part.bm25_body for part in context),
        )

    def search(
        self,
        query: str,
        context_level: ContextLevel = ContextLevel.EVIDENCE,
    ) -> SearchResponse:
        """执行三路召回、RRF、重排、去重和结构化证据组装。"""

        if not query.strip():
            raise ValueError("query cannot be blank")

        route_result = self._route_retriever.retrieve(query)
        fused = reciprocal_rank_fusion(
            route_result.routes,
            rrf_k=self.config.rrf_k,
            limit=self.config.rrf_limit,
        )
        fused_scores = {
            item.chunk_id: item.score
            for item in fused
        }
        selection = self._candidate_reranker.select(query, fused)

        hits = tuple(
            self._build_hit(
                item,
                context_level,
                fused_scores,
                selection,
            )
            for item in selection.final_candidates
        )
        rankings = {
            name: tuple(item.chunk_id for item in items)
            for name, items in route_result.routes.items()
        }
        rankings["rrf"] = tuple(item.chunk_id for item in fused)
        rankings["reranker"] = tuple(
            item.chunk_id
            for item in selection.ranking
        )
        degraded = route_result.degraded + selection.degraded
        trace = SearchTrace(rankings, degraded)
        return SearchResponse(query, context_level, hits, trace)
