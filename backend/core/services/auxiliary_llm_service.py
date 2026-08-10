"""Client for the localhost-only auxiliary Qwen vLLM service."""

from __future__ import annotations

from typing import Any

import httpx


class AuxiliaryLLMUnavailable(RuntimeError):
    """The auxiliary model sidecar is unavailable or returned invalid data."""


class AuxiliaryLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float = 180.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=5.0),
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def is_ready(self) -> bool:
        try:
            response = await self._client.get("/models")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return False

        models = payload.get("data", []) if isinstance(payload, dict) else []
        return any(
            isinstance(item, dict) and item.get("id") == self.model
            for item in models
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float = 0.1,
    ) -> str:
        if max_tokens <= 0:
            raise ValueError("max_tokens 必须大于 0")

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            response = await self._client.post("/chat/completions", json=body)
            response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise AuxiliaryLLMUnavailable(
                "辅助模型服务不可用或返回格式错误"
            ) from error

        if not isinstance(content, str) or not content.strip():
            raise AuxiliaryLLMUnavailable("辅助模型返回了空内容")
        return content.strip()
