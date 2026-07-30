# backend/core/web/sse.py


import json
from typing import Any


def encode_sse(
    event: str,
    data: dict[str, Any],
) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"
