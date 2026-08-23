# backend/agent/rag/agent_api.py

"""
这个文件干什么：把正式检索服务适配为 ESA Agent 可调用的稳定接口。

直白点说就是：在正式检索服务和 Agent 之间做翻译，把复杂检索结果整理成 Agent 熟悉的稳定字典格式。

把正式检索服务适配为 ESA Agent 可调用的稳定接口。
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Callable
from pathlib import PurePath
from typing import Any

from backend.core.utils.models import ToolExecutionResult

from .retrieval.context import (
    estimate_tokens,
    query_aware_excerpt,
    rank_evidence_for_query,
    truncate_text_to_token_budget,
)
from .retrieval.contracts import Evidence, SearchHit, SearchResponse
from .retrieval.service import RetrievalService

_service: RetrievalService | None = None

# B1 remains frozen.  The compatibility retrieval projection uses neutral
# score/ranking names so non-RRF fusion can never be mislabeled as RRF.
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
B2_CONTRACT_VERSION = "retrieve_knowledge.compat.v2"
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
    "retrieval_score",
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
    contexts = _compact_contexts(response.query, hits)
    retrieval_method = str(response.trace.fusion.get("applied_method", "retrieval"))
    return {
        "query": response.query,
        "result_count": len(hits),
        "results": [
            _result_payload(
                response.query,
                hit,
                rank,
                retrieval_method,
                content=contexts[rank - 1],
            )
            for rank, hit in enumerate(hits, start=1)
        ],
        "sources": [
            _source_label(response.query, hit, rank)
            for rank, hit in enumerate(hits, start=1)
        ],
        "context_text": "\n\n".join(contexts),
        "degraded": list(response.trace.degraded),
        "rankings": _compatibility_rankings(response),
    }


def retrieve_knowledge_result(
    query: str,
    top_k: int = 5,
    similarity_threshold: float | None = None,
    service: RetrievalService | None = None,
    token_counter: Callable[[str], int] | None = None,
) -> ToolExecutionResult:
    """Return separated projections for the model, UI, and audit store."""

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
    returned_chunk_ids = {item["chunk_id"] for item in model_content["results"]}
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


def _compatibility_rankings(response: SearchResponse) -> dict[str, list[str]]:
    """Expose only ranking stages that actually ran, under their real names."""

    return {name: list(values) for name, values in response.trace.rankings.items()}


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


def _v2_hit(query: str, hit: SearchHit, rank: int, content: str) -> dict[str, Any]:
    primary = rank_evidence_for_query(query, hit.evidence)[0]
    quote_eligible = bool(hit.evidence) and all(
        item.quote_eligible for item in hit.evidence
    )
    return {
        "rank": rank,
        "chunk_id": hit.chunk_id,
        "content": content,
        "retrieval_score": hit.retrieval_score,
        "rerank_score": hit.rerank_score,
        "source_ref": primary.evidence_id,
        "quote_eligible": quote_eligible,
        "citation_mode": (
            "verbatim_allowed" if quote_eligible else "paraphrase_only_unverified"
        ),
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
    original_token_count = 0

    def citation_policy() -> dict[str, Any]:
        return {
            "verbatim_requires_quote_eligible": True,
            "when_ineligible": "paraphrase_and_disclose_unverified_extraction",
        }

    def build_original(token_count: int) -> dict[str, Any]:
        results = [
            _v2_hit(
                response.query,
                hit,
                rank,
                hit.context_text.strip(),
            )
            for rank, hit in enumerate(hits, start=1)
        ]
        return {
            "contract_version": V2_CONTRACT_VERSION,
            "query": response.query.strip(),
            "result_count": len(results),
            "results": results,
            "citation_policy": citation_policy(),
            "execution": _v2_execution(response),
            "budget": {
                "limit": V2_MODEL_TOKEN_BUDGET,
                "original_token_count": token_count,
                "returned_token_count": token_count,
                "truncated": False,
                "counter": counter_name,
            },
        }

    # Count the exact hypothetical projection before query/result/content
    # pruning.  Both count fields are set to that value, so the reported count
    # includes its own serialized representation rather than relying on an
    # estimate that omits metadata.
    for _ in range(16):
        measured = _serialized_token_count(
            build_original(original_token_count), counter
        )
        if measured == original_token_count:
            break
        original_token_count = measured
    else:
        raise RuntimeError(
            "retrieve_knowledge.v2 original token count did not converge"
        )

    def build(per_result_limit: int, *, truncated: bool) -> dict[str, Any]:
        results = [
            _v2_hit(
                response.query,
                hit,
                rank,
                query_aware_excerpt(hit.context_text, response.query, per_result_limit),
            )
            for rank, hit in enumerate(retained, start=1)
        ]
        return {
            "contract_version": V2_CONTRACT_VERSION,
            "query": returned_query,
            "result_count": len(results),
            "results": results,
            "citation_policy": citation_policy(),
            "execution": _v2_execution(response),
            "budget": {
                "limit": V2_MODEL_TOKEN_BUDGET,
                "original_token_count": original_token_count,
                # Reserve the serialized width/token cost of the final count
                # while searching the content budget.  Writing the real count
                # back later must not push an otherwise exact-fit payload over
                # the hard limit.
                "returned_token_count": V2_MODEL_TOKEN_BUDGET,
                "truncated": truncated,
                "counter": counter_name,
            },
        }

    while (
        retained
        and _serialized_token_count(build(0, truncated=True), counter)
        > V2_MODEL_TOKEN_BUDGET
    ):
        retained.pop()
    while (
        _serialized_token_count(build(0, truncated=True), counter)
        > V2_MODEL_TOKEN_BUDGET
    ):
        if query_limit == 0:
            raise RuntimeError(
                "retrieve_knowledge.v2 fixed metadata exceeds token budget"
            )
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

    was_truncated = (
        returned_query != response.query.strip()
        or len(retained) != len(hits)
        or any(
            query_aware_excerpt(hit.context_text, response.query, low)
            != hit.context_text.strip()
            for hit in retained
        )
    )
    payload = build(low, truncated=was_truncated)
    for _ in range(4):
        count = _serialized_token_count(payload, counter)
        payload["budget"]["returned_token_count"] = count
        if _serialized_token_count(payload, counter) == count:
            break
    if _serialized_token_count(payload, counter) > V2_MODEL_TOKEN_BUDGET:
        raise RuntimeError(
            "retrieve_knowledge.v2 model projection exceeds token budget"
        )
    return payload


def _v2_display_projection(
    response: SearchResponse,
    hits: list[SearchHit],
) -> dict[str, Any]:
    results = []
    for rank, hit in enumerate(hits, start=1):
        primary = rank_evidence_for_query(response.query, hit.evidence)[0]
        locator = primary.locators[0] if primary.locators else None
        results.append(
            {
                "rank": rank,
                "chunk_id": hit.chunk_id,
                "source_ref": primary.evidence_id,
                "source": _display_document_name(primary.document_name),
                "section": " / ".join(primary.section_path) or None,
                "page": _page_number(locator),
                "location": _display_locator(locator),
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
            "retrieval/fusion scores are not reranker probabilities"
        )
    return [
        hit
        for hit in hits
        if hit.rerank_score is not None and hit.rerank_score >= threshold
    ]


def _compact_contexts(query: str, hits: list[SearchHit]) -> list[str]:
    """Allocate the tool-level context budget fairly in ranking order."""

    remaining = B2_CONTEXT_TOKEN_BUDGET
    contexts: list[str] = []
    for position, hit in enumerate(hits):
        remaining_results = len(hits) - position
        fair_share = remaining // remaining_results
        limit = min(B2_RESULT_CONTEXT_TOKEN_LIMIT, fair_share)
        content = query_aware_excerpt(hit.context_text, query, limit)
        contexts.append(content)
        remaining -= estimate_tokens(content)
    return contexts


def _result_payload(
    query: str,
    hit: SearchHit,
    rank: int,
    retrieval_method: str,
    *,
    content: str | None = None,
) -> dict[str, Any]:
    """把一个正式 SearchHit 转换为 Agent 工具结果。"""

    primary = rank_evidence_for_query(query, hit.evidence)[0]
    locator = primary.locators[0] if primary.locators else None
    page = _page_number(locator)
    return {
        "content": hit.context_text if content is None else content,
        "score": (
            hit.rerank_score if hit.rerank_score is not None else hit.retrieval_score
        ),
        "score_type": (
            "reranker" if hit.rerank_score is not None else retrieval_method
        ),
        "rank": rank,
        "source": _display_document_name(primary.document_name),
        "section": " / ".join(primary.section_path) or None,
        "page": page,
        "location": _display_locator(locator),
        "chunk_id": hit.chunk_id,
        "retrieval_score": hit.retrieval_score,
        "rerank_score": hit.rerank_score,
        "context_chunk_ids": list(hit.context_chunk_ids),
        "evidence": [_evidence_payload(item) for item in hit.evidence],
    }


def _page_number(locator: Any) -> int | None:
    if not isinstance(locator, dict) or locator.get("kind") != "page":
        return None
    explicit_page = locator.get("page")
    if isinstance(explicit_page, int) and not isinstance(explicit_page, bool):
        return explicit_page if explicit_page >= 1 else None
    container_index = locator.get("container_index")
    if isinstance(container_index, int) and not isinstance(container_index, bool):
        return container_index + 1
    return None


def _display_locator(locator: Any) -> dict[str, Any] | None:
    """Return one display-safe locator with page fields using one convention."""

    if not isinstance(locator, dict):
        return None
    output = dict(locator)
    page = _page_number(locator)
    if locator.get("kind") == "page" and page is not None:
        output["page"] = page
        output["label"] = f"第{page}页"
    return output


def _evidence_payload(evidence: Evidence) -> dict[str, Any]:
    """序列化证据，同时保留元组字段的 JSON 数组语义。"""

    return dataclasses.asdict(evidence)


def _source_label(query: str, hit: SearchHit, rank: int) -> str:
    """处理 `_source_label` 相关逻辑。"""
    primary = rank_evidence_for_query(query, hit.evidence)[0]
    section = " / ".join(primary.section_path) or "未知章节"
    locations = tuple(_locator_label(locator) for locator in primary.locators)
    location = "、".join(dict.fromkeys(label for label in locations if label))
    suffix = f" · {location}" if location else ""
    source = _display_document_name(primary.document_name)
    return f"【来源 {rank}】{source} · {section}{suffix}"


def _locator_label(locator: Any) -> str:
    """把可选 Locator 转成保守的来源描述，不臆测 parser group 语义。"""

    if not isinstance(locator, dict):
        return ""
    page = _page_number(locator)
    if page is not None:
        return f"第{page}页"
    label = locator.get("label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    index = locator.get("container_index")
    if locator.get("kind") == "page" and isinstance(index, int):
        return f"第{index + 1}页"
    if locator.get("kind") == "group" and isinstance(index, int):
        metadata = locator.get("metadata")
        source_format = (
            metadata.get("source_format") if isinstance(metadata, dict) else None
        )
        prefix = str(source_format).upper() if source_format else "文档"
        return f"{prefix} 解析组 {index + 1}"
    return str(locator.get("container_id") or "")


_DOWNLOAD_SITE_SUFFIX = re.compile(
    r"\s*\([^)]*(?:z-library|z-lib|1lib)[^)]*\)\s*$",
    re.IGNORECASE,
)
_AUTHOR_LATIN_NAME = re.compile(
    r"(?:^|[\s(])(?:[A-Z][\w.'’-]*\s+){1,4}[A-Z][\w.'’-]*(?:$|[),])"
)


def _trailing_parenthesized(value: str) -> tuple[str, str] | None:
    """Split one balanced trailing parenthesized suffix from a filename stem."""

    if not value.endswith(")"):
        return None
    depth = 0
    for position in range(len(value) - 1, -1, -1):
        character = value[position]
        if character == ")":
            depth += 1
        elif character == "(":
            depth -= 1
            if depth == 0:
                return value[:position].rstrip(), value[position + 1 : -1].strip()
    return None


def _looks_like_author_suffix(value: str) -> bool:
    if re.search(r"(?:原书|第\s*\d+\s*版|典藏版)", value):
        return False
    return bool(
        "[美]" in value
        or any(mark in value for mark in ("·", ",", "，"))
        or _AUTHOR_LATIN_NAME.search(value)
    )


def _display_document_name(document_name: str) -> str:
    """Remove known acquisition noise while preserving an auditable raw name."""

    original = PurePath(document_name).name.strip()
    stem = original
    extension = PurePath(original).suffix
    if extension:
        stem = original[: -len(extension)]
    cleaned = re.sub(r"(?:[_\s-]+origin)\s*$", "", stem, flags=re.IGNORECASE)
    cleaned, site_count = _DOWNLOAD_SITE_SUFFIX.subn("", cleaned)
    changed = cleaned != stem or site_count > 0
    trailing = _trailing_parenthesized(cleaned.rstrip())
    if changed and trailing is not None and _looks_like_author_suffix(trailing[1]):
        cleaned = trailing[0]
    cleaned = cleaned.strip(" _-")
    return cleaned if changed and cleaned else original
