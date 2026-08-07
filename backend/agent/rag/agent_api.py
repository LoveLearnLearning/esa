# backend/agent/rag/agent_api.py

"""

这个文件干什么：把正式检索服务适配为 ESA Agent 可调用的稳定接口。

直白点说就是：在正式检索服务和 Agent 之间做翻译，把复杂检索结果整理成 Agent 熟悉的稳定字典格式。

把正式检索服务适配为 ESA Agent 可调用的稳定接口。
"""

from __future__ import annotations

import dataclasses
from typing import Any

from .retrieval.contracts import Evidence, SearchHit, SearchResponse
from .retrieval.service import RetrievalService

_service: RetrievalService | None = None


def configure_retrieval_service(service: RetrievalService) -> None:
    """注入由 ESA 生命周期创建并持有的检索服务。"""

    global _service
    _service = service


def reset_retrieval_service() -> None:
    """移除当前服务；仅供生命周期清理和隔离测试使用。"""

    global _service
    _service = None


def get_retrieval_service() -> RetrievalService:
    """返回已配置服务，不在导入阶段隐式建库或加载模型。"""

    if _service is None:
        raise RuntimeError(
            "RAG retrieval service is not configured; "
            "configure it during the ESA application lifespan"
        )
    return _service


def retrieve_knowledge_payload(
    query: str,
    top_k: int = 5,
    similarity_threshold: float | None = None,
) -> dict[str, Any]:
    """执行检索并转换成旧 ESA 工具熟悉、同时保留 Evidence 的 JSON 结构。"""

    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if similarity_threshold is not None and not 0 <= similarity_threshold <= 1:
        raise ValueError("similarity_threshold must be between 0 and 1")

    response = get_retrieval_service().search(query)
    hits = _apply_rerank_threshold(response, similarity_threshold)[:top_k]
    return {
        "query": response.query,
        "result_count": len(hits),
        "results": [
            _result_payload(hit, rank) for rank, hit in enumerate(hits, start=1)
        ],
        "sources": [_source_label(hit, rank) for rank, hit in enumerate(hits, start=1)],
        "context_text": "\n\n".join(hit.context_text for hit in hits),
        "degraded": list(response.trace.degraded),
        "rankings": {
            name: list(chunk_ids) for name, chunk_ids in response.trace.rankings.items()
        },
    }


def knowledge_base_stats() -> dict[str, Any]:
    """返回当前注入服务的 Collection、后端和查询配置。"""

    service = get_retrieval_service()
    return {
        "collection_id": service.collection.manifest.collection_id,
        "document_count": len(service.collection.documents),
        "total_chunks": len(service.collection.chunks),
        "embedding_model": service.embedding.model_name,
        "reranker_model": (
            service.reranker.model_name if service.reranker is not None else None
        ),
        "index_backend": type(service.index).__qualname__,
        "config": dataclasses.asdict(service.config),
    }


def _apply_rerank_threshold(
    response: SearchResponse,
    threshold: float | None,
) -> list[SearchHit]:
    """只对有明确 Reranker 概率的结果应用 0 到 1 阈值。"""

    hits = list(response.hits)
    if threshold is None:
        return hits
    if any(hit.rerank_score is None for hit in hits):
        raise RuntimeError(
            "similarity_threshold requires an active reranker; "
            "RRF scores are rank-fusion scores, not probabilities"
        )
    return [
        hit
        for hit in hits
        if hit.rerank_score is not None and hit.rerank_score >= threshold
    ]


def _result_payload(hit: SearchHit, rank: int) -> dict[str, Any]:
    """把一个正式 SearchHit 转换为 Agent 工具结果。"""

    primary = hit.evidence[0]
    return {
        "content": hit.context_text,
        "score": hit.rerank_score if hit.rerank_score is not None else hit.rrf_score,
        "score_type": "reranker" if hit.rerank_score is not None else "rrf",
        "rank": rank,
        "source": primary.document_name,
        "section": " / ".join(primary.section_path) or None,
        "page": primary.page_indexes[0] + 1 if primary.page_indexes else None,
        "chunk_id": hit.chunk_id,
        "rrf_score": hit.rrf_score,
        "rerank_score": hit.rerank_score,
        "context_chunk_ids": list(hit.context_chunk_ids),
        "evidence": [_evidence_payload(item) for item in hit.evidence],
    }


def _evidence_payload(evidence: Evidence) -> dict[str, Any]:
    """序列化证据，同时保留元组字段的 JSON 数组语义。"""

    return dataclasses.asdict(evidence)


def _source_label(hit: SearchHit, rank: int) -> str:
    """生成兼容旧 ESA 展示习惯的简短来源标签。"""

    primary = hit.evidence[0]
    section = " / ".join(primary.section_path) or "未知章节"
    pages = ", ".join(str(index + 1) for index in primary.page_indexes) or "未知"
    return f"【来源 {rank}】{primary.document_name} · {section} · 第{pages}页"
