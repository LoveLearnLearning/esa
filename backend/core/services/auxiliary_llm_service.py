# backend/core/services/auxiliary_llm_service.py

"""Client for the localhost-only auxiliary multimodal Qwen vLLM service."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from backend.core.utils.config import LOG_PROMPTS


logger = logging.getLogger(__name__)


class AuxiliaryLLMUnavailable(RuntimeError):
    """The auxiliary model sidecar is unavailable or returned invalid data."""


class AuxiliaryLLMClient:
    """封装 `AuxiliaryLLMClient` 的状态与行为。"""
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float = 180.0,
    ) -> None:
        """初始化 `AuxiliaryLLMClient` 实例。"""
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=5.0),
            trust_env=False,
        )

    async def close(self) -> None:
        """释放当前对象持有的资源。"""
        await self._client.aclose()

    async def is_ready(self) -> bool:
        """判断 `ready` 相关数据。"""
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
        """调用 OpenAI-compatible Chat API。

        ``messages[*].content`` 既可以是文本，也可以是包含 ``image_url``
        的多模态 content parts；媒体统一由上游编码为受控的 Data URL。
        """
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
        if LOG_PROMPTS:
            serialized = json.dumps(messages, ensure_ascii=False, default=str)
            logger.info(
                "LLM prompt start model=auxiliary model_name=%s chars=%d",
                self.model,
                len(serialized),
            )
            logger.info(
                "LLM prompt body model=auxiliary model_name=%s\n%s",
                self.model,
                serialized,
            )
            logger.info(
                "LLM prompt end model=auxiliary model_name=%s",
                self.model,
            )
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
