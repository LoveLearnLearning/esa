"""One Agent-facing retrieval contract over selected public/personal scopes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from backend.core.utils.models import ToolExecutionResult

from . import agent_api
from .retrieval.context import (
    estimate_tokens,
    query_aware_excerpt,
    truncate_text_to_token_budget,
)


CONTRACT_VERSION = "retrieve_knowledge.unified.v1"
MODEL_TOKEN_BUDGET = 2048
RESULT_TOKEN_LIMIT = 512
RRF_K = 60
VALID_SOURCES = frozenset({"personal", "public"})


async def retrieve_selected_knowledge(
    *,
    query: str,
    top_k: int,
    similarity_threshold: float | None = None,
    knowledge_sources: Sequence[str],
    user_id: str,
    knowledge_base_id: str | None,
    public_service: Any | None,
    personal_service: Any | None,
    token_counter: Callable[[str], int] | None = None,
) -> ToolExecutionResult:
    """Retrieve only scopes selected in trusted turn context and fuse by rank."""

    sources = tuple(dict.fromkeys(knowledge_sources))
    if not sources or not set(sources) <= VALID_SOURCES:
        raise ValueError("at least one valid knowledge source is required")
    if not query.strip():
        raise ValueError("query cannot be blank")
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")
    if similarity_threshold is not None and not 0 <= similarity_threshold <= 1:
        raise ValueError("similarity_threshold must be between 0 and 1")

    public_task = None
    personal_task = None
    if "public" in sources:
        if public_service is None:
            raise RuntimeError("public knowledge service is not configured")
        public_task = asyncio.to_thread(
            agent_api.retrieve_knowledge_result,
            query=query,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
            service=public_service,
            token_counter=token_counter,
        )
    if "personal" in sources and personal_service is not None:
        personal_arguments: dict[str, Any] = {
            "user_id": user_id,
            "query": query,
            "top_k": top_k,
        }
        if knowledge_base_id is not None:
            personal_arguments["knowledge_base_id"] = knowledge_base_id
        personal_task = personal_service.search(**personal_arguments)

    pending = [task for task in (public_task, personal_task) if task is not None]
    resolved = await asyncio.gather(*pending) if pending else []
    cursor = iter(resolved)
    public_result = next(cursor) if public_task is not None else None
    personal_result = next(cursor) if personal_task is not None else None
    if "personal" in sources and personal_service is None:
        personal_result = _empty_personal(query, "personal_knowledge_base_unavailable")

    candidates: list[dict[str, Any]] = []
    if isinstance(public_result, ToolExecutionResult):
        candidates.extend(_public_candidates(public_result))
    if isinstance(personal_result, Mapping):
        candidates.extend(_personal_candidates(personal_result))

    fused = _fuse(candidates, sources, top_k)
    degraded = _degraded(public_result, personal_result)
    counter = token_counter or estimate_tokens
    counter_name = "agent_tokenizer" if token_counter is not None else "fallback"
    model_content = _model_projection(
        query=query,
        candidates=fused,
        sources=sources,
        degraded=degraded,
        counter=counter,
        counter_name=counter_name,
    )
    returned_keys = {
        (item["scope"], item["chunk_id"]) for item in model_content["results"]
    }
    returned = [
        item
        for item in fused
        if (item["scope"], item["chunk_id"]) in returned_keys
    ]
    display_content = {
        "contract_version": CONTRACT_VERSION,
        "query": query,
        "selected_sources": list(sources),
        "result_count": len(returned),
        "results": [
            {
                "rank": rank,
                "scope": item["scope"],
                **item["display"],
            }
            for rank, item in enumerate(returned, start=1)
        ],
        "execution": _execution(sources, degraded),
    }
    audit_metadata = {
        "contract_version": CONTRACT_VERSION,
        "selected_sources": list(sources),
        "fusion": {
            "method": "source_rrf" if len(sources) > 1 else "single_source_rank",
            "rrf_k": RRF_K if len(sources) > 1 else None,
            "ranking": [
                {
                    "scope": item["scope"],
                    "chunk_id": item["chunk_id"],
                    "source_rank": item["source_rank"],
                    "fused_score": item["fused_score"],
                }
                for item in fused
            ],
        },
        "public": public_result.audit_metadata if public_result is not None else None,
        "personal": dict(personal_result) if personal_result is not None else None,
        "model_budget": dict(model_content["budget"]),
    }
    return ToolExecutionResult(model_content, display_content, audit_metadata)


def _empty_personal(query: str, reason: str) -> dict[str, Any]:
    return {
        "query": query,
        "result_count": 0,
        "results": [],
        "degraded": [reason],
        "rankings": {},
    }


def _public_candidates(result: ToolExecutionResult) -> list[dict[str, Any]]:
    model_results = result.model_content.get("results", [])
    display_by_chunk = {
        item["chunk_id"]: item
        for item in result.display_content.get("results", [])
    }
    candidates = []
    for source_rank, item in enumerate(model_results, start=1):
        chunk_id = str(item["chunk_id"])
        display = dict(display_by_chunk.get(chunk_id, {}))
        display.pop("rank", None)
        candidates.append(
            {
                "scope": "public",
                "chunk_id": chunk_id,
                "source_rank": source_rank,
                "content": str(item.get("content", "")),
                "source_ref": str(item.get("source_ref", chunk_id)),
                "quote_eligible": bool(item.get("quote_eligible", False)),
                "citation_mode": str(
                    item.get("citation_mode", "paraphrase_only_unverified")
                ),
                "display": display,
            }
        )
    return candidates


def _personal_candidates(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    for source_rank, raw in enumerate(result.get("results", []), start=1):
        item = dict(raw)
        chunk_id = str(item.get("chunk_id", ""))
        evidence = item.get("evidence", [])
        primary = evidence[0] if evidence else {}
        quote_eligible = bool(evidence) and all(
            isinstance(value, Mapping)
            and bool(value.get("quote_eligible", False))
            for value in evidence
        )
        candidates.append(
            {
                "scope": "personal",
                "chunk_id": chunk_id,
                "source_rank": source_rank,
                "content": str(item.get("content", "")),
                "source_ref": str(primary.get("evidence_id", chunk_id)),
                "quote_eligible": quote_eligible,
                "citation_mode": (
                    "verbatim_allowed"
                    if quote_eligible
                    else "paraphrase_only_unverified"
                ),
                "display": {
                    "chunk_id": chunk_id,
                    "source_ref": str(primary.get("evidence_id", chunk_id)),
                    "source": item.get("source"),
                    "section": item.get("section"),
                    "page": _personal_page(item.get("location")),
                    "location": item.get("location"),
                    "quote_eligible": quote_eligible,
                },
            }
        )
    return candidates


def _personal_page(location: Any) -> int | None:
    if not isinstance(location, Mapping):
        return None
    page = location.get("page")
    return page if isinstance(page, int) else None


def _fuse(
    candidates: list[dict[str, Any]],
    sources: Sequence[str],
    limit: int,
) -> list[dict[str, Any]]:
    source_order = {source: rank for rank, source in enumerate(sources)}
    for item in candidates:
        item["fused_score"] = 1 / (RRF_K + item["source_rank"])
    return sorted(
        candidates,
        key=lambda item: (
            -item["fused_score"],
            source_order[item["scope"]],
            item["source_rank"],
            item["chunk_id"],
        ),
    )[:limit]


def _degraded(public_result: Any, personal_result: Any) -> list[str]:
    values: list[str] = []
    if isinstance(public_result, ToolExecutionResult):
        values.extend(public_result.model_content.get("execution", {}).get("degraded", []))
    if isinstance(personal_result, Mapping):
        values.extend(personal_result.get("degraded", []))
    return list(dict.fromkeys(str(value) for value in values))


def _execution(sources: Sequence[str], degraded: Sequence[str]) -> dict[str, Any]:
    return {
        "selected_sources": list(sources),
        "ranking_method": (
            "source_rrf" if len(sources) > 1 else "single_source_rank"
        ),
        "degraded": list(degraded),
    }


def _serialized_tokens(value: object, counter: Callable[[str], int]) -> int:
    return counter(json.dumps(value, ensure_ascii=False, default=str))


def _model_projection(
    *,
    query: str,
    candidates: list[dict[str, Any]],
    sources: Sequence[str],
    degraded: Sequence[str],
    counter: Callable[[str], int],
    counter_name: str,
) -> dict[str, Any]:
    retained = list(candidates)
    returned_query = query.strip()
    query_limit = 256
    original_count = 0

    def result_payload(item: Mapping[str, Any], rank: int, content: str) -> dict[str, Any]:
        return {
            "rank": rank,
            "scope": item["scope"],
            "chunk_id": item["chunk_id"],
            "content": content,
            "source_ref": item["source_ref"],
            "quote_eligible": item["quote_eligible"],
            "citation_mode": item["citation_mode"],
        }

    def build(items: Sequence[Mapping[str, Any]], content_limit: int | None, count: int, truncated: bool) -> dict[str, Any]:
        results = []
        for rank, item in enumerate(items, start=1):
            content = str(item["content"]).strip()
            if content_limit is not None:
                content = query_aware_excerpt(content, query, content_limit)
            results.append(result_payload(item, rank, content))
        return {
            "contract_version": CONTRACT_VERSION,
            "query": returned_query,
            "selected_sources": list(sources),
            "result_count": len(results),
            "results": results,
            "citation_policy": {
                "verbatim_requires_quote_eligible": True,
                "when_ineligible": "paraphrase_and_disclose_unverified_extraction",
            },
            "execution": _execution(sources, degraded),
            "budget": {
                "limit": MODEL_TOKEN_BUDGET,
                "original_token_count": original_count,
                "returned_token_count": count,
                "truncated": truncated,
                "counter": counter_name,
            },
        }

    for _ in range(16):
        measured = _serialized_tokens(
            build(candidates, None, original_count, False), counter
        )
        if measured == original_count:
            break
        original_count = measured
    else:
        raise RuntimeError("unified retrieval original token count did not converge")

    while retained and _serialized_tokens(
        build(retained, 0, MODEL_TOKEN_BUDGET, True), counter
    ) > MODEL_TOKEN_BUDGET:
        retained.pop()
    while _serialized_tokens(
        build(retained, 0, MODEL_TOKEN_BUDGET, True), counter
    ) > MODEL_TOKEN_BUDGET:
        if query_limit == 0:
            raise RuntimeError("unified retrieval metadata exceeds token budget")
        query_limit //= 2
        returned_query = truncate_text_to_token_budget(query, query_limit)

    low, high = 0, RESULT_TOKEN_LIMIT
    while low < high:
        middle = (low + high + 1) // 2
        if _serialized_tokens(
            build(retained, middle, MODEL_TOKEN_BUDGET, False), counter
        ) <= MODEL_TOKEN_BUDGET:
            low = middle
        else:
            high = middle - 1
    was_truncated = (
        returned_query != query.strip()
        or len(retained) != len(candidates)
        or any(
            query_aware_excerpt(str(item["content"]), query, low)
            != str(item["content"]).strip()
            for item in retained
        )
    )
    payload = build(retained, low, MODEL_TOKEN_BUDGET, was_truncated)
    for _ in range(4):
        count = _serialized_tokens(payload, counter)
        payload["budget"]["returned_token_count"] = count
        if _serialized_tokens(payload, counter) == count:
            break
    if _serialized_tokens(payload, counter) > MODEL_TOKEN_BUDGET:
        raise RuntimeError("unified retrieval model projection exceeds token budget")
    return payload
