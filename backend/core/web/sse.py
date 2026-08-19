# backend/core/web/sse.py

"""提供 `sse` 相关功能。"""


import json
from typing import Any


def encode_sse(
    event: str,
    data: dict[str, Any],
) -> str:
    """编码 `sse` 相关数据。

    Args:
        event: str => `event` 参数。
        data: dict[str, Any] => 输入数据。

    Returns:
        str => 处理结果。
    """
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"
