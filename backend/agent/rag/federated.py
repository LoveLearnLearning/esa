"""Federate tenant-scoped personal retrieval with the shared knowledge base."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

from backend.agent.rag.agent_api import retrieve_knowledge_payload


_RRF_K = 60
_MAX_TOP_K = 20


async def retrieve_federated_knowledge_payload(
    *,
    user_id: str,
    query: str,
    top_k: int = 5,
    similarity_threshold: float | None = None,
    public_service: Any = None,
    personal_service: Any = None,
) -> dict[str, Any]:
    """Query both knowledge scopes and return one balanced ranked response.

    The two backends expose scores with different semantics, so raw scores must
    not be compared directly.  Results are combined by their rank within each
    scope, which also prevents a much larger shared collection from crowding
    every personal result out of the final context.
    """

    if not user_id:
        raise ValueError("trusted user_id is required")
    if not query.strip():
        raise ValueError("query cannot be blank")
    if not 1 <= top_k <= _MAX_TOP_K:
        raise ValueError("top_k must be between 1 and 20")

    candidate_limit = min(_MAX_TOP_K, max(top_k * 2, top_k))
    public_call = asyncio.to_thread(
        retrieve_knowledge_payload,
        query,
        candidate_limit,
        similarity_threshold,
        public_service,
    )
    if personal_service is None:
        personal_call = _empty_personal(query)
    else:
        personal_call = personal_service.search(
            user_id=user_id,
            query=query,
            top_k=candidate_limit,
        )

    personal_result, public_result = await asyncio.gather(
        personal_call,
        public_call,
        return_exceptions=True,
    )
    personal = _result_or_degraded(
        personal_result,
        query=query,
        scope="personal",
    )
    public = _result_or_degraded(
        public_result,
        query=query,
        scope="public",
    )
    return _merge_payloads(query, personal, public, top_k=top_k)


async def _empty_personal(query: str) -> dict[str, Any]:
    return {
        "query": query,
        "result_count": 0,
        "results": [],
        "degraded": ["personal_knowledge_base_unavailable"],
        "rankings": {},
    }


def _result_or_degraded(
    result: Any,
    *,
    query: str,
    scope: str,
) -> Mapping[str, Any]:
    if isinstance(result, BaseException):
        if isinstance(result, asyncio.CancelledError):
            raise result
        return {
            "query": query,
            "result_count": 0,
            "results": [],
            "degraded": [f"{scope}_retrieval_failed"],
            "rankings": {},
        }
    if not isinstance(result, Mapping):
        return {
            "query": query,
            "result_count": 0,
            "results": [],
            "degraded": [f"{scope}_retrieval_invalid_response"],
            "rankings": {},
        }
    return result


def _merge_payloads(
    query: str,
    personal: Mapping[str, Any],
    public: Mapping[str, Any],
    *,
    top_k: int,
) -> dict[str, Any]:
    candidates: list[tuple[float, int, int, str, dict[str, Any]]] = []
    scope_payloads = (("personal", personal), ("public", public))
    for scope_order, (scope, payload) in enumerate(scope_payloads):
        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            continue
        for position, raw in enumerate(raw_results, start=1):
            if not isinstance(raw, Mapping):
                continue
            local_rank = raw.get("rank")
            if not isinstance(local_rank, int) or local_rank <= 0:
                local_rank = position
            federated_score = 1.0 / (_RRF_K + local_rank)
            item = dict(raw)
            item["knowledge_scope"] = scope
            item["scope_rank"] = local_rank
            item["scope_score"] = raw.get("score")
            item["federated_score"] = federated_score
            item["score"] = federated_score
            item["score_type"] = "federated_rrf"
            chunk_id = str(raw.get("chunk_id") or f"rank-{position}")
            candidates.append(
                (federated_score, local_rank, scope_order, chunk_id, item)
            )

    candidates.sort(key=lambda value: (-value[0], value[1], value[2], value[3]))
    selected = [value[-1] for value in candidates[:top_k]]
    for rank, item in enumerate(selected, start=1):
        item["rank"] = rank

    degraded = []
    for scope, payload in scope_payloads:
        raw_degraded = payload.get("degraded", [])
        if isinstance(raw_degraded, list):
            degraded.extend(f"{scope}:{reason}" for reason in raw_degraded)

    return {
        "query": query,
        "result_count": len(selected),
        "results": selected,
        "sources": [_source_label(item, rank) for rank, item in enumerate(selected, 1)],
        "context_text": "\n\n".join(
            _context_block(item, rank) for rank, item in enumerate(selected, 1)
        ),
        "degraded": degraded,
        "rankings": {
            "federated": [
                f"{item['knowledge_scope']}:{item.get('chunk_id', '')}"
                for item in selected
            ],
            "personal": _chunk_ids(personal),
            "public": _chunk_ids(public),
        },
        "federation": {
            "mode": "personal_and_public",
            "personal_candidates": _result_count(personal),
            "public_candidates": _result_count(public),
        },
    }


def _result_count(payload: Mapping[str, Any]) -> int:
    results = payload.get("results", [])
    return len(results) if isinstance(results, list) else 0


def _chunk_ids(payload: Mapping[str, Any]) -> list[str]:
    results = payload.get("results", [])
    if not isinstance(results, list):
        return []
    return [
        str(item.get("chunk_id", ""))
        for item in results
        if isinstance(item, Mapping)
    ]


def _scope_label(scope: Any) -> str:
    return "个人知识库" if scope == "personal" else "公共知识库"


def _source_label(item: Mapping[str, Any], rank: int) -> str:
    source = str(item.get("source") or "未知来源")
    section = item.get("section")
    suffix = f" · {section}" if isinstance(section, str) and section else ""
    return (
        f"【来源 {rank}｜{_scope_label(item.get('knowledge_scope'))}】"
        f"{source}{suffix}"
    )


def _context_block(item: Mapping[str, Any], rank: int) -> str:
    content = str(item.get("content") or "")
    return f"{_source_label(item, rank)}\n{content}"
