"""Serializers and token accounting for model-facing views."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping

try:
    from backend.core.utils.token_estimation import estimate_tokens as _estimate_tokens
except Exception:  # pragma: no cover - standalone invocation fallback
    _estimate_tokens = None


def json_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def text_compact(results: list[Mapping[str, Any]]) -> str:
    return "\n\n".join(f"[{item['ref']}]\n{item['content']}" for item in results)


def token_count(value: Any, counter: Callable[[str], int] | None = None) -> int:
    text = value if isinstance(value, str) else json_compact(value)
    if counter is not None:
        return counter(text)
    if _estimate_tokens is not None:
        return _estimate_tokens(text)
    # Dependency-free approximation: JSON punctuation/ASCII averages roughly
    # four characters per token; CJK characters are close to one token each.
    cjk = sum("\u4e00" <= char <= "\u9fff" for char in text)
    ascii_chars = sum(ord(char) < 128 for char in text)
    other = len(text) - cjk - ascii_chars
    return max(1, int(ascii_chars / 4 + cjk + other))
