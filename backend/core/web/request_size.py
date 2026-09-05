"""ASGI request-size guard applied before multipart parsing and spooling."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable


class _RequestTooLarge(Exception):
    pass


class PersonalKnowledgeBaseRequestSizeMiddleware:
    """Bound only the personal batch-upload route before FastAPI parses it."""

    def __init__(self, app: Callable, *, max_bytes: int) -> None:
        if max_bytes <= 0:
            raise ValueError("personal request max bytes must be positive")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable):
        if not self._applies(scope):
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", ())}
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_bytes:
                    await self._reject(send)
                    return
            except ValueError:
                await self._reject(send)
                return
        observed = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal observed
            message = await receive()
            if message.get("type") == "http.request":
                observed += len(message.get("body", b""))
                if observed > self.max_bytes:
                    raise _RequestTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestTooLarge:
            await self._reject(send)

    @staticmethod
    def _applies(scope: dict[str, Any]) -> bool:
        if scope.get("type") != "http" or scope.get("method") != "POST":
            return False
        path = str(scope.get("path", "")).rstrip("/")
        if path.endswith("/me/knowledge-base/files"):
            return True
        segments = [segment for segment in path.split("/") if segment]
        return (
            len(segments) >= 3
            and segments[-3] == "libraries"
            and bool(segments[-2])
            and segments[-1] == "files"
        )

    @staticmethod
    async def _reject(send: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        body = json.dumps(
            {"detail": "个人知识库上传请求体超过限制"},
            ensure_ascii=False,
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
