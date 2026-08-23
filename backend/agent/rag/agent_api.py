# backend/agent/rag/agent_api.py

"""
这个文件干什么：把正式检索服务适配为 ESA Agent 可调用的稳定接口。

直白点说就是：在正式检索服务和 Agent 之间做翻译，把复杂检索结果整理成 Agent 熟悉的稳定字典格式。

把正式检索服务适配为 ESA Agent 可调用的稳定接口。
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

from backend.core.utils.models import ToolExecutionResult

from .retrieval.context import estimate_tokens, truncate_text_to_token_budget
from .retrieval.contracts import Evidence, SearchHit, SearchResponse
from .retrieval.service import RetrievalService

_service: RetrievalService | None = None

# B1/B2 v1: these tuples are the frozen JSON surface. Additive or breaking
# changes require a new contract version and fixture migration.
B1_CONTRACT_VERSION = "get_knowledge_base_stats.v1"
B1_TOP_LEVEL_KEYS = (
    "collection_id",
    "document_count",
    "total_chunks",
    "embedding_model",
    "reranker_model",
    "index_backend",
    "config",
)
B2_CONTRACT_VERSION = "retrieve_knowledge.v1"
B2_CONTEXT_TOKEN_BUDGET = 2048
B2_RESULT_CONTEXT_TOKEN_LIMIT = 512
B2_TOP_LEVEL_KEYS = (
    "query",
    "result_count",
    "results",
    "sources",
    "context_text",
    "degraded",
    "rankings",
)
B2_RESULT_KEYS = (
    "content",
    "score",
    "score_type",
    "rank",
    "source",
    "section",
    "page",
    "location",
    "chunk_id",
    "rrf_score",
    "rerank_score",
    "context_chunk_ids",
    "evidence",
)
V2_CONTRACT_VERSION = "retrieve_knowledge.v2"
V2_MODEL_TOKEN_BUDGET = 2048
V2_RESULT_TOKEN_LIMIT = 512


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
    service: RetrievalService | None = None,
) -> dict[str, Any]:
    """执行检索并转换成旧 ESA 工具熟悉、同时保留 Evidence 的 JSON 结构。"""

    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if similarity_threshold is not None and not 0 <= similarity_threshold <= 1:
        raise ValueError("similarity_threshold must be between 0 and 1")

    active_service = service or get_retrieval_service()
    response = active_service.search(query)
    hits = _apply_rerank_threshold(response, similarity_threshold)[:top_k]
    contexts = _compact_contexts(hits)
    return {
        "query": response.query,
        "result_count": len(hits),
        "results": [
            _result_payload(hit, rank, content=contexts[rank - 1])
            for rank, hit in enumerate(hits, start=1)
        ],
        "sources": [_source_label(hit, rank) for rank, hit in enumerate(hits, start=1)],
        "context_text": "\n\n".join(contexts),
        "degraded": list(response.trace.degraded),
        "rankings": _legacy_rankings(response, active_service.config.rerank_limit),
    }


def retrieve_knowledge_v2_result(
    query: str,
    top_k: int = 5,
    similarity_threshold: float | None = None,
    service: RetrievalService | None = None,
    token_counter: Callable[[str], int] | None = None,
) -> ToolExecutionResult:
    """Return semantic v2 projections for the model, UI, and audit store."""

    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if similarity_threshold is not None and not 0 <= similarity_threshold <= 1:
        raise ValueError("similarity_threshold must be between 0 and 1")

    active_service = service or get_retrieval_service()
    response = active_service.search(query)
    hits = _apply_rerank_threshold(response, similarity_threshold)[:top_k]
    counter = token_counter or estimate_tokens
    counter_name = "agent_tokenizer" if token_counter is not None else "fallback"
    model_content = _v2_model_projection(response, hits, counter, counter_name)
    returned_chunk_ids = {
        item["chunk_id"] for item in model_content["results"]
    }
    display_content = _v2_display_projection(
        response,
        [hit for hit in hits if hit.chunk_id in returned_chunk_ids],
    )
    audit_metadata = {
        "contract_version": V2_CONTRACT_VERSION,
        "response": dataclasses.asdict(response),
        "model_budget": dict(model_content["budget"]),
    }
    return ToolExecutionResult(model_content, display_content, audit_metadata)


def _legacy_rankings(
    response: SearchResponse,
    rerank_limit: int,
) -> dict[str, list[str]]:
    """Preserve the frozen v1 ranking names behind an explicit legacy adapter."""

    output = {
        name: list(values)
        for name, values in response.trace.rankings.items()
        if name not in {"fusion", "final", "reranker"}
    }
    fusion = list(response.trace.rankings.get("fusion", ()))
    output["rrf"] = fusion
    output["reranker"] = list(
        response.trace.rankings.get("reranker", tuple(fusion[:rerank_limit]))
    )
    return output


def _serialized_token_count(payload: object, counter: Callable[[str], int]) -> int:
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    return counter(serialized)


def _v2_execution(response: SearchResponse) -> dict[str, Any]:
    fusion = response.trace.fusion
    weight_names = (
        "dense_weight",
        "bm25_body_weight",
        "bm25_heading_weight",
    )
    return {
        "configured_method": fusion.get("configured_method"),
        "applied_method": fusion.get("applied_method"),
        "ranking_method": fusion.get("ranking_method", "retrieval"),
        "reranker_applied": response.trace.reranker_applied,
        "weights": {name: fusion[name] for name in weight_names if name in fusion},
        "degraded": list(response.trace.degraded),
    }


def _v2_hit(hit: SearchHit, rank: int, content: str) -> dict[str, Any]:
    primary = hit.evidence[0]
    return {
        "rank": rank,
        "chunk_id": hit.chunk_id,
        "content": content,
        "retrieval_score": hit.retrieval_score,
        "rerank_score": hit.rerank_score,
        "source_ref": primary.evidence_id,
        "quote_eligible": bool(hit.evidence)
        and all(item.quote_eligible for item in hit.evidence),
    }


def _v2_model_projection(
    response: SearchResponse,
    hits: list[SearchHit],
    counter: Callable[[str], int],
    counter_name: str,
) -> dict[str, Any]:
    """Budget the final serialized model JSON, including every metadata field."""

    retained = list(hits)
    query_limit = 256
    returned_query = truncate_text_to_token_budget(response.query, query_limit)

    def build(per_result_limit: int, *, truncated: bool) -> dict[str, Any]:
        results = [
            _v2_hit(
                hit,
                rank,
                truncate_text_to_token_budget(hit.context_text, per_result_limit),
            )
            for rank, hit in enumerate(retained, start=1)
        ]
        return {
            "contract_version": V2_CONTRACT_VERSION,
            "query": returned_query,
            "result_count": len(results),
            "results": results,
            "execution": _v2_execution(response),
            "budget": {
                "limit": V2_MODEL_TOKEN_BUDGET,
                "returned_token_count": 0,
                "truncated": truncated,
                "counter": counter_name,
            },
        }

    while retained and _serialized_token_count(build(0, truncated=True), counter) > V2_MODEL_TOKEN_BUDGET:
        retained.pop()
    while _serialized_token_count(build(0, truncated=True), counter) > V2_MODEL_TOKEN_BUDGET:
        if query_limit == 0:
            raise RuntimeError("retrieve_knowledge.v2 fixed metadata exceeds token budget")
        query_limit //= 2
        returned_query = truncate_text_to_token_budget(response.query, query_limit)

    low, high = 0, V2_RESULT_TOKEN_LIMIT
    while low < high:
        middle = (low + high + 1) // 2
        candidate = build(middle, truncated=False)
        if _serialized_token_count(candidate, counter) <= V2_MODEL_TOKEN_BUDGET:
            low = middle
        else:
            high = middle - 1

    was_truncated = returned_query != response.query.strip() or len(retained) != len(hits) or any(
        truncate_text_to_token_budget(hit.context_text, low) != hit.context_text.strip()
        for hit in retained
    )
    payload = build(low, truncated=was_truncated)
    for _ in range(4):
        count = _serialized_token_count(payload, counter)
        payload["budget"]["returned_token_count"] = count
        if _serialized_token_count(payload, counter) == count:
            break
    if _serialized_token_count(payload, counter) > V2_MODEL_TOKEN_BUDGET:
        raise RuntimeError("retrieve_knowledge.v2 model projection exceeds token budget")
    return payload


def _v2_display_projection(
    response: SearchResponse,
    hits: list[SearchHit],
) -> dict[str, Any]:
    results = []
    for rank, hit in enumerate(hits, start=1):
        primary = hit.evidence[0]
        locator = primary.locators[0] if primary.locators else None
        results.append(
            {
                "rank": rank,
                "chunk_id": hit.chunk_id,
                "source_ref": primary.evidence_id,
                "source": primary.document_name,
                "section": " / ".join(primary.section_path) or None,
                "page": _page_number(locator),
                "location": dict(locator) if locator else None,
                "quote_eligible": bool(hit.evidence)
                and all(item.quote_eligible for item in hit.evidence),
            }
        )
    return {
        "contract_version": V2_CONTRACT_VERSION,
        "query": response.query,
        "result_count": len(results),
        "results": results,
        "execution": _v2_execution(response),
    }


def knowledge_base_stats(service: RetrievalService | None = None) -> dict[str, Any]:
    """返回当前注入服务的 Collection、后端和查询配置。"""

    service = service or get_retrieval_service()
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


def _compact_contexts(hits: list[SearchHit]) -> list[str]:
    """Allocate the tool-level context budget fairly in ranking order."""

    remaining = B2_CONTEXT_TOKEN_BUDGET
    contexts: list[str] = []
    for position, hit in enumerate(hits):
        remaining_results = len(hits) - position
        fair_share = remaining // remaining_results
        limit = min(B2_RESULT_CONTEXT_TOKEN_LIMIT, fair_share)
        content = truncate_text_to_token_budget(hit.context_text, limit)
        contexts.append(content)
        remaining -= estimate_tokens(content)
    return contexts


def _result_payload(
    hit: SearchHit,
    rank: int,
    *,
    content: str | None = None,
) -> dict[str, Any]:
    """把一个正式 SearchHit 转换为 Agent 工具结果。"""

    primary = hit.evidence[0]
    locator = primary.locators[0] if primary.locators else None
    page = _page_number(locator)
    return {
        "content": hit.context_text if content is None else content,
        "score": (
            hit.rerank_score
            if hit.rerank_score is not None
            else hit.retrieval_score
        ),
        "score_type": "reranker" if hit.rerank_score is not None else "rrf",
        "rank": rank,
        "source": primary.document_name,
        "section": " / ".join(primary.section_path) or None,
        "page": page,
        "location": dict(locator) if locator else None,
        "chunk_id": hit.chunk_id,
        "rrf_score": hit.retrieval_score,
        "rerank_score": hit.rerank_score,
        "context_chunk_ids": list(hit.context_chunk_ids),
        "evidence": [_evidence_payload(item) for item in hit.evidence],
    }


def _page_number(locator: Any) -> int | None:
    if (
        isinstance(locator, dict)
        and locator.get("kind") == "page"
        and isinstance(locator.get("container_index"), int)
    ):
        return int(locator["container_index"]) + 1
    return None


def _evidence_payload(evidence: Evidence) -> dict[str, Any]:
    """序列化证据，同时保留元组字段的 JSON 数组语义。"""

    return dataclasses.asdict(evidence)


def _source_label(hit: SearchHit, rank: int) -> str:

    """处理 `_source_label` 相关逻辑。"""
    primary = hit.evidence[0]
    section = " / ".join(primary.section_path) or "未知章节"
    locations = tuple(_locator_label(locator) for locator in primary.locators)
    location = "、".join(dict.fromkeys(label for label in locations if label))
    suffix = f" · {location}" if location else ""
    return f"【来源 {rank}】{primary.document_name} · {section}{suffix}"


def _locator_label(locator: Any) -> str:
    """把可选 Locator 转成保守的来源描述，不臆测 parser group 语义。"""

    if not isinstance(locator, dict):
        return ""
    label = locator.get("label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    index = locator.get("container_index")
    if locator.get("kind") == "page" and isinstance(index, int):
        return f"第{index + 1}页"
    if locator.get("kind") == "group" and isinstance(index, int):
        metadata = locator.get("metadata")
        source_format = metadata.get("source_format") if isinstance(metadata, dict) else None
        prefix = str(source_format).upper() if source_format else "文档"
        return f"{prefix} 解析组 {index + 1}"
    return str(locator.get("container_id") or "")
