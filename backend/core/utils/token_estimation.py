"""Small, dependency-optional token estimation helper for prompt budgets."""

from __future__ import annotations

from typing import Protocol


class _TokenEncoding(Protocol):
    def encode(self, text: str) -> list[int]:
        ...


TOKEN_ENCODING: _TokenEncoding | None

try:  # pragma: no cover - optional dependency
    from tiktoken import get_encoding

    TOKEN_ENCODING = get_encoding("cl100k_base")
except Exception:  # noqa: BLE001
    TOKEN_ENCODING = None


def estimate_tokens(text: str) -> int:
    """Estimate model tokens, accounting for CJK text when tiktoken is absent."""
    if TOKEN_ENCODING is not None:
        return max(1, len(TOKEN_ENCODING.encode(text)))

    cjk = 0
    ascii_count = 0
    other = 0
    for char in text:
        code = ord(char)
        if code <= 0x007F:
            ascii_count += 1
        elif 0x4E00 <= code <= 0x9FFF:
            cjk += 1
        else:
            other += 1
    return max(1, int(ascii_count / 4 + cjk * 1.5 + other))
