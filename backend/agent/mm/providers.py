# backend/agent/mm/providers.py

"""Tokenizer 与 OpenAI-compatible VLM provider。"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from .contracts import VisualAnalysis
from backend.core.log.logger import get_pipeline_logger


logger = get_pipeline_logger("MM", __name__)


def _fingerprint(payload: object) -> str:
    """处理 `_fingerprint` 相关逻辑。"""
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class TransformersTokenCounter:
    """封装 `TransformersTokenCounter` 的状态与行为。"""
    model_name: str
    _tokenizer: Any = field(init=False, default=None, repr=False)

    def _load(self) -> Any:
        """加载 `load` 相关数据。"""
        if self._tokenizer is None:
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        return self._tokenizer

    def count_tokens(self, text: str) -> int:
        """统计 `tokens` 相关数据。"""
        return len(self._load().encode(text, add_special_tokens=False))


@dataclass(frozen=True)
class OpenAICompatibleVisionProvider:
    """封装 `OpenAICompatibleVisionProvider` 的状态与行为。"""
    base_url: str
    model_name: str
    model_revision: str | None = None
    api_key: str | None = None
    timeout: float = 120.0
    attempts: int = 2
    provider_name: str = "openai-compatible"

    def __post_init__(self) -> None:
        """完成实例初始化后的校验与派生字段构建。"""
        if self.timeout <= 0 or self.attempts <= 0:
            raise ValueError("VLM timeout and attempts must be positive")

    @property
    def configuration_fingerprint(self) -> str:
        """处理 `configuration_fingerprint` 相关逻辑。"""
        return _fingerprint(
            {
                "provider": self.provider_name,
                "base_url": self.base_url.rstrip("/"),
                "model": self.model_name,
                "revision": self.model_revision,
                "response_contract": "mm-visual-analysis-0.2",
                "thinking": False,
            }
        )

    async def analyze(
        self, image: bytes, media_type: str, prompt: str
    ) -> VisualAnalysis:
        """处理 `analyze` 相关逻辑。

        Args:
            image: bytes => `image` 参数。
            media_type: str => `media_type` 参数。
            prompt: str => `prompt` 参数。

        Returns:
            VisualAnalysis => 处理结果。
        """
        encoded = base64.b64encode(image).decode("ascii")
        payload = {
            "model": self.model_name,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{encoded}"
                            },
                        },
                    ],
                }
            ],
        }
        headers = {"Content-Type": "application/json"}
        key = self.api_key or os.environ.get("MM_VLM_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                logger.info(
                    "VLM request started model=%s attempt=%d",
                    self.model_name,
                    attempt,
                )
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                logger.info("VLM request completed model=%s", self.model_name)
                return _parse_visual_analysis(content)
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "VLM request failed model=%s attempt=%d error_type=%s",
                    self.model_name,
                    attempt,
                    type(exc).__name__,
                )
        raise RuntimeError(f"VLM request failed after {self.attempts} attempts") from last_error


def _parse_visual_analysis(content: object) -> VisualAnalysis:
    """解析 `visual analysis` 相关数据。"""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("VLM response content must be a non-empty string")
    value = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    decoder = json.JSONDecoder()
    last_error: ValueError | None = None
    for position, character in enumerate(value):
        if character != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(value, position)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        try:
            return _visual_analysis_from_mapping(parsed)
        except ValueError as exc:
            last_error = exc
    if last_error is not None:
        raise ValueError("VLM response contains no valid visual analysis JSON") from last_error
    raise ValueError("VLM response contains no JSON object")


def _visual_analysis_from_mapping(parsed: object) -> VisualAnalysis:
    """处理 `_visual_analysis_from_mapping` 相关逻辑。"""
    if not isinstance(parsed, dict):
        raise ValueError("VLM response must be a JSON object")
    description = parsed.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("VLM response description must be non-empty")
    visible = parsed.get("visible_text", "")
    content_type = parsed.get("content_type", "image")
    if not isinstance(visible, str) or not isinstance(content_type, str):
        raise ValueError("VLM response text fields must be strings")
    if not content_type.strip():
        raise ValueError("VLM response content_type must be non-empty")
    return VisualAnalysis(description.strip(), visible.strip(), content_type.strip())
