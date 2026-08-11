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


def split_text_spans(
    text: str,
    max_chars: int,
    *,
    min_chars: int = 0,
    overlap_sentences: int = 0,
) -> list[tuple[str, int, int]]:
    """优先按自然边界切分，并避免可重新分配的极短尾段。"""

    if max_chars <= 0:
        raise ValueError("max_chars 必须为正")
    if min_chars < 0:
        raise ValueError("min_chars 不能为负")
    if overlap_sentences not in {0, 1}:
        raise ValueError("overlap_sentences 当前只支持 0 或 1")
    base: list[tuple[str, int, int]] = []
    cursor = 0
    while cursor < len(text):
        chosen = _choose_end(text, cursor, max_chars)
        piece = _trimmed_span(text, cursor, chosen)
        if piece is not None:
            base.append(piece)
        cursor = max(chosen, cursor + 1)
    base = _rebalance_short_tail(text, base, max_chars, min_chars)
    if not overlap_sentences:
        return base

    output = [base[0]] if base else []
    for index, (value, start, end) in enumerate(base[1:], start=1):
        previous_start, previous_end = base[index - 1][1:]
        candidate = _last_sentence_start(text, previous_start, previous_end)
        if candidate is not None:
            if end - candidate <= max_chars:
                overlapped = _trimmed_span(text, candidate, end)
                if overlapped is not None:
                    output.append(overlapped)
                    continue
            else:
                subdivisions = split_text_spans(
                    text[candidate:end],
                    max_chars,
                    min_chars=min_chars,
                )
                if subdivisions:
                    output.extend(
                        (piece, candidate + piece_start, candidate + piece_end)
                        for piece, piece_start, piece_end in subdivisions
                    )
                    continue
        output.append((value, start, end))
    return output


def _rebalance_short_tail(
    text: str,
    spans: list[tuple[str, int, int]],
    max_chars: int,
    min_chars: int,
) -> list[tuple[str, int, int]]:
    """把最后一个过短跨度的边界向前移动到自然边界。"""

    minimum = min(min_chars, max_chars)
    if minimum <= 0 or len(spans) < 2 or len(spans[-1][0]) >= minimum:
        return spans
    previous = spans[-2]
    tail = spans[-1]
    lower = previous[1] + minimum
    upper = min(previous[1] + max_chars, tail[2] - minimum)
    if lower > upper:
        return spans
    boundary = _preferred_boundary(text, lower, upper)
    left = _trimmed_span(text, previous[1], boundary)
    right = _trimmed_span(text, boundary, tail[2])
    if (
        left is None
        or right is None
        or len(left[0]) > max_chars
        or len(right[0]) > max_chars
        or len(left[0]) < minimum
        or len(right[0]) < minimum
    ):
        return spans
    return [*spans[:-2], left, right]


def _preferred_boundary(text: str, lower: int, upper: int) -> int:
    """在合法区间内优先选择最靠后的换行或句末。"""

    newline = text.rfind("\n", lower, upper + 1)
    sentence_ends = [
        match.end() for match in _SENTENCE_END.finditer(text, lower, upper)
    ]
    candidates = [item for item in (newline + 1, *sentence_ends) if lower <= item <= upper]
    return max(candidates, default=upper)


def _last_sentence_start(text: str, start: int, end: int) -> int | None:
    """返回已输出片段最后一句的起点，找不到可靠边界时不重叠。"""

    boundaries = [match.end() for match in _SENTENCE_END.finditer(text, start, end)]
    if len(boundaries) < 2:
        return None
    sentence_start = boundaries[-2]
    while sentence_start < end and text[sentence_start].isspace():
        sentence_start += 1
    return sentence_start if sentence_start < end else None


def _choose_end(text: str, cursor: int, max_chars: int) -> int:
    """为当前文本片段选择不超过硬上限的结束位置。"""

    if len(text) - cursor <= max_chars:
        return len(text)
    ceiling = cursor + max_chars
    minimum = cursor + max(1, max_chars // 3)
    # ``ceiling`` is an exclusive end offset. Including the character at that
    # index can return ``ceiling + 1`` and violate the hard max_chars contract.
    newline = text.rfind("\n", minimum, ceiling)
    if newline >= minimum:
        return newline + 1
    matches = list(_SENTENCE_END.finditer(text, minimum, ceiling))
    return matches[-1].end() if matches else ceiling
