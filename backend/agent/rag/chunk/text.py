# backend/agent/rag/chunk/text.py

"""

这个文件干什么：Chunk 文本边界切分工具。

直白点说就是：在不超过长度上限的前提下，优先沿自然文字边界切开长文本。

Chunk 文本边界切分工具。
"""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"[。！？；.!?;]\s*")


def _trimmed_span(
    text: str,
    start: int,
    end: int,
) -> tuple[str, int, int] | None:
    """裁掉边界空白，同时保留相对于原文的偏移。"""

    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (text[start:end], start, end) if end > start else None


def split_text_spans(text: str, max_chars: int) -> list[tuple[str, int, int]]:
    """优先按换行、句末标点切分，必要时使用硬边界。"""

    if max_chars <= 0:
        raise ValueError("max_chars 必须为正")
    output: list[tuple[str, int, int]] = []
    cursor = 0
    while cursor < len(text):
        chosen = _choose_end(text, cursor, max_chars)
        piece = _trimmed_span(text, cursor, chosen)
        if piece is not None:
            output.append(piece)
        cursor = max(chosen, cursor + 1)
    return output


def _choose_end(text: str, cursor: int, max_chars: int) -> int:
    """为当前文本片段选择不超过硬上限的结束位置。"""

    if len(text) - cursor <= max_chars:
        return len(text)
    ceiling = cursor + max_chars
    minimum = cursor + max(1, max_chars // 3)
    newline = text.rfind("\n", minimum, ceiling + 1)
    if newline >= minimum:
        return newline + 1
    matches = list(_SENTENCE_END.finditer(text, minimum, ceiling + 1))
    return matches[-1].end() if matches else ceiling
