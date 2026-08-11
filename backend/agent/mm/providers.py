"""Tokenizer 与 OpenAI-compatible VLM provider。"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from .contracts import VisualAnalysis


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class TransformersTokenCounter:
    model_name: str
    _tokenizer: Any = field(init=False, default=None, repr=False)

    def _load(self) -> Any:
        if self._tokenizer is None:
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        return self._tokenizer

    def count_tokens(self, text: str) -> int:
        return len(self._load().encode(text, add_special_tokens=False))


@dataclass(frozen=True)
class OpenAICompatibleVisionProvider:
    base_url: str
    model_name: str
    model_revision: str | None = None
    api_key: str | None = None
    timeout: float = 120.0
    attempts: int = 2
    provider_name: str = "openai-compatible"

    def __post_init__(self) -> None:
        if self.timeout <= 0 or self.attempts <= 0:
            raise ValueError("VLM timeout and attempts must be positive")

    @property
    def configuration_fingerprint(self) -> str:
        return _fingerprint(
            {
                "provider": self.provider_name,
                "base_url": self.base_url.rstrip("/"),
                "model": self.model_name,
                "revision": self.model_revision,
                "response_contract": "mm-visual-analysis-0.1",
            }
        )

    async def analyze(
        self, image: bytes, media_type: str, prompt: str
    ) -> VisualAnalysis:
        encoded = base64.b64encode(image).decode("ascii")
        payload = {
            "model": self.model_name,
            "temperature": 0,
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
        for _attempt in range(self.attempts):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return _parse_visual_analysis(content)
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = exc
        raise RuntimeError(f"VLM request failed after {self.attempts} attempts") from last_error


def _parse_visual_analysis(content: object) -> VisualAnalysis:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("VLM response content must be a non-empty string")
    value = content.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        value = "\n".join(lines[1:-1]).strip()
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("VLM response must be a JSON object")
    description = parsed.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("VLM response description must be non-empty")
    visible = parsed.get("visible_text", "")
    content_type = parsed.get("content_type", "image")
    if not isinstance(visible, str) or not isinstance(content_type, str):
        raise ValueError("VLM response text fields must be strings")
    return VisualAnalysis(description.strip(), visible.strip(), content_type.strip())

