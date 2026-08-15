# backend/agent/workspaces/history.py

"""History normalization applied before every production Agent run."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_UNSUPPORTED_TOOL_CALLS_PATTERN = re.compile(
    r"<[^<>]*tool_calls(?:\s[^<>]*)?>",
    re.IGNORECASE,
)


def sanitize_qwen_history(
    history: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Remove legacy plural tool-call protocol turns and their tool results."""

    sanitized: list[dict[str, Any]] = []
    skip_following_tools = False
    for item in history:
        message = dict(item)
        role = message.get("role")
        content = message.get("content", "")
        if role == "assistant":
            skip_following_tools = isinstance(content, str) and bool(
                _UNSUPPORTED_TOOL_CALLS_PATTERN.search(content)
            )
            if skip_following_tools:
                continue
        elif role == "tool":
            if skip_following_tools:
                continue
        else:
            skip_following_tools = False
        sanitized.append(message)
    return sanitized
