"""Helpers for identifying the one practice question still awaiting an answer."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


_PRACTICE_HEADER_RE = re.compile(
    r"【练习题｜知识点[：:]\s*(?P<kp_id>[^】]+)】"
)


def pending_practice_kp_label(
    history: Sequence[Mapping[str, object]] | None,
) -> str | None:
    """Return the label from the latest unanswered practice prompt, if any."""
    for message in reversed(history or ()):
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        match = _PRACTICE_HEADER_RE.search(content)
        if match:
            return match.group("kp_id").strip()
    return None
