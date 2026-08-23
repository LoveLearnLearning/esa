# backend/agent/rag/retrieval/service.py

"""

这个文件干什么：作为第一阶段核心检索链的薄编排层，协调召回、融合、重排和证据输出。

直白点说就是：像总调度员一样按顺序叫召回、融合、重排和证据模块干活，自己只负责把流程串起来。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import time

from ..chunk import Chunk
from ..collection import LoadedChunkCollection
from .context import ContextBuilder, EvidenceAssembler
from .calibration import (
    CosineScoreCalibrator,
    RobustMinMaxScoreCalibrator,
    ScoreCalibrator,
)
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
from .fusion import (
    FusionResult,
    reciprocal_rank_fusion,
    score_level_weighted_fusion,
    weighted_reciprocal_rank_fusion,
)
from .reranking import CandidateReranker, CandidateSelection
from .routing import RouteRetriever
from backend.core.log.logger import get_pipeline_logger


logger = get_pipeline_logger("RAG", __name__)


@dataclass
class RetrievalService:
    """通过多个单一职责组件编排第一阶段检索流程。"""

    collection: LoadedChunkCollection
    index: RetrievalIndex
    embedding: EmbeddingProvider
    reranker: Reranker | None
    config: RetrievalConfig = field(default_factory=RetrievalConfig)
    score_calibrators: Mapping[str, ScoreCalibrator] = field(
        default_factory=lambda: {
            "dense": CosineScoreCalibrator(),
            "bm25_body": RobustMinMaxScoreCalibrator(0.0, 20.0),
            "bm25_heading": RobustMinMaxScoreCalibrator(0.0, 20.0),
        }
    )

    def __post_init__(self) -> None:
        """建立 Chunk 映射，并初始化召回、重排和上下文组件。"""

        self._chunks = {chunk.chunk_id: chunk for chunk in self.collection.chunks}
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
            getattr(self.embedding, "count_tokens", None),
        )

    def warmup(self) -> None:
        """Eagerly load process-owned local inference models."""

        for provider in (self.embedding, self.reranker):
            warmup = getattr(provider, "warmup", None)
            if callable(warmup):
                warmup()

    def _build_hit(
        self,
        item: RankedItem,
        context_level: ContextLevel,
        fused_scores: Mapping[str, float],
        selection: CandidateSelection,
        context: tuple[Chunk, ...],
    ) -> SearchHit:
        """把最终候选转换为包含引用与章节上下文的 SearchHit。"""

        chunk: Chunk = self._chunks[item.chunk_id]
        evidence_chunks = (
            chunk,
            *(part for part in context if part.chunk_id != chunk.chunk_id),
        )
        return SearchHit(
            chunk_id=chunk.chunk_id,
            retrieval_score=fused_scores[chunk.chunk_id],
            rerank_score=selection.rerank_scores.get(chunk.chunk_id),
            evidence=tuple(
                evidence
                for part in evidence_chunks
                for evidence in EvidenceAssembler.build(
                    part,
                    self.collection.document_names[part.document_id],
                )
            ),
            context_chunk_ids=tuple(part.chunk_id for part in context),
            context_text="\n\n".join(part.bm25_body for part in context),
        )

    def search(
        self,
        query: str,
        context_level: ContextLevel = ContextLevel.EVIDENCE,
    ) -> SearchResponse:
        """执行三路召回、fusion、串行重排、去重和结构化证据组装。"""

        if not query.strip():
            raise ValueError("query cannot be blank")

        started = time.monotonic()
        logger.info("retrieval started query_chars=%d", len(query))

        route_result = self._route_retriever.retrieve(query)
        fused, fusion_trace = self._fuse(query, route_result.routes)
        fused_scores = {item.chunk_id: item.score for item in fused}
        selection = self._candidate_reranker.select(query, fused)

        selected_chunks = [
            self._chunks[item.chunk_id] for item in selection.final_candidates
        ]
        contexts = self._context_builder.plan(
            selected_chunks,
            context_level,
            self.config.max_context_tokens,
        )

        hits = tuple(
            self._build_hit(
                item,
                context_level,
                fused_scores,
                selection,
                contexts[item.chunk_id],
            )
            for item in selection.final_candidates
            if item.chunk_id in contexts
        )
        rankings = {
            name: tuple(item.chunk_id for item in items)
            for name, items in route_result.routes.items()
        }
        rankings["fusion"] = tuple(item.chunk_id for item in fused)
        if selection.reranker_applied:
            rankings["reranker"] = tuple(item.chunk_id for item in selection.ranking)
        rankings["final"] = tuple(hit.chunk_id for hit in hits)
        degraded = route_result.degraded + selection.degraded
        raw_scores = {
            name: {item.chunk_id: item.score for item in items}
            for name, items in route_result.routes.items()
        }
        fusion_trace = {
            **fusion_trace,
            "reranker_applied": selection.reranker_applied,
            "ranking_method": (
                "reranker"
                if selection.reranker_applied
                else "retrieval"
            ),
        }
        trace = SearchTrace(
            rankings=rankings,
            degraded=degraded,
            raw_scores=raw_scores,
            fusion=fusion_trace,
            reranker_applied=selection.reranker_applied,
        )
        response = SearchResponse(query, context_level, hits, trace)
        logger.info(
            "retrieval completed hits=%d degraded=%d elapsed_seconds=%.3f",
            len(hits),
            len(degraded),
            time.monotonic() - started,
        )
        return response

    def _fuse(
        self,
        query: str,
        routes: Mapping[str, list[RankedItem]],
    ) -> tuple[list[RankedItem], dict[str, float | str | bool]]:
        """按显式配置选择可消融融合方式，并记录实际权重。"""

        method = self.config.fusion_method
        if method == "dense":
            fused = list(routes.get("dense", ()))[: self.config.rrf_limit]
            applied_method = "dense"
            actual_weights: dict[str, float] = {
                "dense_weight": 1.0,
                "bm25_body_weight": 0.0,
                "bm25_heading_weight": 0.0,
            }
            if not fused:
                fused = reciprocal_rank_fusion(
                    {
                        name: values
                        for name, values in routes.items()
                        if name != "dense"
                    },
                    rrf_k=self.config.rrf_k,
                    limit=self.config.rrf_limit,
                )
                applied_method = "lexical_rrf_fallback"
                actual_weights = {
                    "dense_weight": 0.0,
                    "bm25_body_weight": 1.0,
                    "bm25_heading_weight": 1.0,
                }
            return fused, {
                "configured_method": method,
                "applied_method": applied_method,
                **actual_weights,
            }
        if method == "equal_rrf":
            return (
                reciprocal_rank_fusion(
                    routes, rrf_k=self.config.rrf_k, limit=self.config.rrf_limit
                ),
                {
                    "configured_method": method,
                    "applied_method": method,
                    "dense_weight": 1.0,
                    "bm25_body_weight": 1.0,
                    "bm25_heading_weight": 1.0,
                },
            )
        if method == "weighted_rrf":
            lexical_weight = 1.0 - self.config.dense_weight
            weights = {
                "dense_weight": self.config.dense_weight,
                "bm25_body_weight": lexical_weight * self.config.lexical_body_weight,
                "bm25_heading_weight": lexical_weight
                * (1.0 - self.config.lexical_body_weight),
            }
            route_weights = {
                name: weights[f"{name}_weight"]
                for name in ("dense", "bm25_body", "bm25_heading")
            }
            return (
                weighted_reciprocal_rank_fusion(
                    routes,
                    route_weights,
                    rrf_k=self.config.rrf_k,
                    limit=self.config.rrf_limit,
                ),
                {"configured_method": method, "applied_method": method, **weights},
            )
        effective_alpha = self.config.dense_weight
        if not routes.get("dense"):
            effective_alpha = 0.0
        result: FusionResult = score_level_weighted_fusion(
            routes,
            self.score_calibrators,
            query=query,
            alpha=effective_alpha,
            beta=self.config.lexical_body_weight,
            limit=self.config.rrf_limit,
            lexical_gate=None if self.config.lexical_gate_enabled else 1.0,
        )
        lexical_weight = (1.0 - effective_alpha) * result.lexical_confidence
        return list(result.ranking), {
            "configured_method": method,
            "applied_method": method,
            "dense_weight": effective_alpha,
            "bm25_body_weight": lexical_weight * self.config.lexical_body_weight,
            "bm25_heading_weight": lexical_weight
            * (1.0 - self.config.lexical_body_weight),
            "lexical_body_weight": self.config.lexical_body_weight,
            "lexical_confidence": result.lexical_confidence,
            "lexical_gate_enabled": self.config.lexical_gate_enabled,
        }
