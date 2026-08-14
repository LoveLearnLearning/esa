"""Deterministic lexical CoreMemory retrieval with bounded output."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from backend.agent.memories.core_memory_models import CoreMemoryRecord

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def _terms(text: str) -> set[str]:
    lowered = text.casefold()
    terms = {item for item in _TOKEN_RE.findall(lowered) if len(item) > 1}
    terms.update(
        lowered[index : index + 2] for index in range(max(0, len(lowered) - 1))
    )
    return terms


def _clip_tokens(text: str, limit: int) -> tuple[str, int]:
    # A deterministic conservative estimator that works for Chinese and Latin text.
    max_chars = limit * 3
    clipped = text if len(text) <= max_chars else text[:max_chars].rstrip() + "..."
    return clipped, max(1, (len(clipped) + 2) // 3)


class CoreMemoryRetrieval:
    version = "lexical.v1"

    def rank(
        self,
        records: list[CoreMemoryRecord],
        query: str,
        *,
        category: str | None = None,
        limit: int = 5,
        total_token_budget: int = 600,
        item_token_budget: int = 160,
    ) -> list[dict[str, object]]:
        query = " ".join(query.split()).casefold()
        if not query:
            return []
        query_terms = _terms(query)
        now = datetime.now(timezone.utc)
        workspace_keys = {
            item.memory_key for item in records if item.scope.scope_type == "workspace"
        }
        scored: list[tuple[float, str, CoreMemoryRecord]] = []
        for item in records:
            if item.status != "active":
                continue
            if item.expires_at and datetime.fromisoformat(item.expires_at) <= now:
                continue
            if category and item.category != category:
                continue
            if item.scope.scope_type == "global" and item.memory_key in workspace_keys:
                continue
            haystack = f"{item.memory_key} {item.category} {item.content}".casefold()
            item_terms = _terms(haystack)
            overlap = len(query_terms & item_terms)
            phrase = 8 if query in haystack else 0
            key_exact = 20 if query == item.memory_key.casefold() else 0
            category_hit = 2 if item.category.casefold() in query_terms else 0
            review_penalty = (
                0.5
                if item.review_after
                and datetime.fromisoformat(item.review_after) <= now
                else 1.0
            )
            score = (key_exact + phrase + overlap + category_hit) * review_penalty
            if score <= 0:
                continue
            scored.append((score, item.updated_at, item))
        scored.sort(key=lambda value: (value[0], value[1]), reverse=True)

        results: list[dict[str, object]] = []
        remaining = total_token_budget
        for score, _updated, item in scored[: max(1, min(limit, 20))]:
            content, tokens = _clip_tokens(
                item.content, min(item_token_budget, remaining)
            )
            if tokens > remaining:
                break
            payload = item.to_dict()
            payload.update(
                {"content": content, "score": score, "estimated_tokens": tokens}
            )
            results.append(payload)
            remaining -= tokens
            if remaining <= 0:
                break
        return results
