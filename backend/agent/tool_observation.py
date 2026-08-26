"""Structure-preserving projection of Tool observations for model context."""

from __future__ import annotations

import json
import re
from typing import Any

from backend.core.utils.config import (
    TOOL_RESULT_CONTENT_MAX_TOKENS,
    TOOL_RESULT_CUMULATIVE_MAX_TOKENS,
    TOOL_RESULT_DEFAULT_MAX_TOKENS,
    TOOL_RESULT_SKILL_MAX_TOKENS,
    TOOL_RESULT_STATE_MAX_TOKENS,
)
from backend.core.utils.token_estimation import estimate_tokens


CONTENT_TOOLS = frozenset(
    {
        "retrieve_knowledge",
        "retrieve_personal_knowledge",
        "web_search",
        "arxiv_search",
        "parse_pdf_attachment",
        "parse_word_attachment",
        "parse_presentation_attachment",
        "parse_spreadsheet_attachment",
        "parse_image_attachment",
    }
)
STATE_TOOLS = frozenset(
    {
        "record_learning_evidence",
        "save_core_memory",
        "propose_core_memory",
        "delete_core_memory",
        "get_mastery_level",
        "get_review_timing",
        "get_teaching_context",
        "get_mastery_report",
        "get_weak_prerequisites",
        "get_learning_evidence_summary",
        "recommend_practice",
        "get_knowledge_base_stats",
        "search_core_memories",
        "get_core_memories",
    }
)
PRIORITY_KEYS = (
    "ok",
    "allowed",
    "saved",
    "deleted",
    "duplicate",
    "error",
    "reason",
    "detail",
    "status",
    "action_id",
    "id",
    "kp_id",
    "memory_id",
    "attachment_id",
    "count",
    "result",
    "content",
)


def observation_budget(tool_name: str) -> int:
    """Return the configured per-observation budget."""
    if tool_name == "load_skill":
        return TOOL_RESULT_SKILL_MAX_TOKENS
    if tool_name in CONTENT_TOOLS:
        return TOOL_RESULT_CONTENT_MAX_TOKENS
    if tool_name in STATE_TOOLS:
        return TOOL_RESULT_STATE_MAX_TOKENS
    return TOOL_RESULT_DEFAULT_MAX_TOKENS


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _bounded_text(value: str, token_limit: int) -> object:
    if estimate_tokens(_json(value)) <= token_limit:
        return value
    pieces = [
        item.strip()
        for item in re.split(r"(?<=[。！？.!?])|\n+", value)
        if item.strip()
    ]
    kept: list[str] = []
    for piece in pieces:
        candidate = {
            "text": "\n".join((*kept, piece)),
            "_projection": {"truncated": True, "original_chars": len(value)},
        }
        if estimate_tokens(_json(candidate)) > token_limit:
            break
        kept.append(piece)
    if kept:
        return {
            "text": "\n".join(kept),
            "_projection": {"truncated": True, "original_chars": len(value)},
        }
    return {
        "_projection": {
            "omitted": True,
            "reason": "oversized_scalar",
            "original_chars": len(value),
        }
    }


def _project(value: Any, token_limit: int) -> Any:
    if estimate_tokens(_json(value)) <= token_limit:
        return value
    if isinstance(value, str):
        return _bounded_text(value, token_limit)
    if isinstance(value, list):
        projected: list[Any] = []
        omitted = 0
        for item in value:
            remaining = max(32, token_limit - estimate_tokens(_json(projected)))
            candidate = projected + [_project(item, remaining)]
            if estimate_tokens(_json(candidate)) > token_limit:
                omitted += 1
                continue
            projected = candidate
        omitted += max(0, len(value) - len(projected) - omitted)
        if omitted:
            marker = {"_projection": {"omitted_items": omitted}}
            if estimate_tokens(_json(projected + [marker])) <= token_limit:
                projected.append(marker)
        return projected
    if isinstance(value, dict):
        ordered_keys = [key for key in PRIORITY_KEYS if key in value]
        ordered_keys.extend(key for key in value if key not in ordered_keys)
        projected: dict[str, Any] = {}
        omitted: list[str] = []
        for key in ordered_keys:
            remaining = max(32, token_limit - estimate_tokens(_json(projected)))
            candidate = {**projected, key: _project(value[key], remaining)}
            if estimate_tokens(_json(candidate)) <= token_limit:
                projected = candidate
            else:
                omitted.append(str(key))
        if omitted:
            marker = {
                "truncated": True,
                "omitted_fields": omitted,
            }
            candidate = {**projected, "_projection": marker}
            if estimate_tokens(_json(candidate)) <= token_limit:
                projected = candidate
        return projected
    return {
        "_projection": {
            "omitted": True,
            "reason": "oversized_scalar",
            "type": type(value).__name__,
        }
    }


def project_tool_result(tool_name: str, result: Any) -> str:
    """Serialize one model-facing observation within its Tool-specific budget."""
    return _json(_project(result, observation_budget(tool_name)))


def compact_tool_observations(
    messages: list[dict],
    *,
    max_tokens: int = TOOL_RESULT_CUMULATIVE_MAX_TOKENS,
) -> None:
    """Replace oldest model-only observations with compact valid JSON receipts."""
    tool_messages = [message for message in messages if message.get("role") == "tool"]
    total = sum(estimate_tokens(str(message.get("content", ""))) for message in tool_messages)
    for message in tool_messages:
        if total <= max_tokens:
            break
        content = str(message.get("content", ""))
        try:
            payload = json.loads(content)
        except (TypeError, ValueError):
            payload = {}
        receipt = {
            "_projection": {"compacted": True},
            "tool": message.get("name"),
        }
        if isinstance(payload, dict):
            for key in ("ok", "allowed", "saved", "deleted", "status", "action_id", "id", "kp_id"):
                if key in payload:
                    receipt[key] = payload[key]
        replacement = _json(receipt)
        message["content"] = replacement
        total -= estimate_tokens(content) - estimate_tokens(replacement)
