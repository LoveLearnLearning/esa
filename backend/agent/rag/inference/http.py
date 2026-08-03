# backend/agent/rag/inference/http.py

"""

这个文件干什么：通过本地 HTTP 服务执行 Embedding 与 Reranker 推理。

直白点说就是：把文本发给本地模型 HTTP 服务，再把返回值整理成向量或重排分数。

通过本地 HTTP 服务执行 Embedding 与 Reranker 推理。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..fingerprints import configuration_sha256
from .errors import InferenceUnavailable


def _post_json(
    url: str,
    payload: dict[str, Any],
    timeout: float,
    api_key: str | None,
) -> dict[str, Any]:
    """只向显式配置的地址发送 JSON，并统一包装传输故障。"""

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise InferenceUnavailable(
            f"local inference request failed: {url}: {exc}"
        ) from exc


@dataclass(frozen=True)
class VLLMEmbeddingProvider:
    """通过 vLLM OpenAI-compatible Embeddings API 调用 Qwen3。"""

    base_url: str
    model_name: str = "Qwen/Qwen3-Embedding-4B"
    api_key: str | None = None
    timeout: float = 120.0
    query_instruction: str = (
        "Given a web search query, retrieve relevant passages that answer the query"
    )

    @property
    def configuration_fingerprint(self) -> str:
        """记录影响向量内容的服务端可见配置。"""

        return configuration_sha256(
            {
                "backend": "vllm-embeddings-api-0.1",
                "model_name": self.model_name,
                "query_instruction": self.query_instruction,
            }
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """调用 vLLM Embeddings API 批量编码文本。"""

        if not texts:
            return []
        data = _post_json(
            f"{self.base_url.rstrip('/')}/v1/embeddings",
            {
                "model": self.model_name,
                "input": list(texts),
                "encoding_format": "float",
            },
            self.timeout,
            self.api_key,
        ).get("data", [])
        try:
            ordered = sorted(data, key=lambda item: item["index"])
            vectors = [
                [float(value) for value in item["embedding"]]
                for item in ordered
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise InferenceUnavailable("embedding response is incomplete") from exc
        if len(vectors) != len(texts):
            raise InferenceUnavailable(
                "embedding response count does not match request"
            )
        return vectors

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """不添加查询指令，编码待入库文档。"""

        return self.embed(texts)

    def embed_query(self, query: str) -> list[float]:
        """添加 Qwen3 查询指令后编码问题。"""

        prompt = f"Instruct: {self.query_instruction}\nQuery: {query}"
        return self.embed([prompt])[0]


@dataclass(frozen=True)
class VLLMReranker:
    """通过 vLLM Score API 对查询与候选文档批量打分。"""

    base_url: str
    model_name: str = "Qwen/Qwen3-Reranker-4B"
    api_key: str | None = None
    timeout: float = 120.0

    @property
    def configuration_fingerprint(self) -> str:
        """记录影响重排输出的服务端可见配置。"""

        return configuration_sha256(
            {"backend": "vllm-score-api-0.1", "model_name": self.model_name}
        )

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        """调用 Score API，并按输入下标恢复候选顺序。"""

        if not documents:
            return []
        response = _post_json(
            f"{self.base_url.rstrip('/')}/score",
            {
                "model": self.model_name,
                "queries": query,
                "documents": list(documents),
            },
            self.timeout,
            self.api_key,
        )
        scores: list[float | None] = [None] * len(documents)
        try:
            for item in response.get("data", []):
                scores[int(item["index"])] = float(item["score"])
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise InferenceUnavailable("reranker response is incomplete") from exc
        if any(score is None for score in scores):
            raise InferenceUnavailable("reranker response count does not match request")
        return [float(score) for score in scores if score is not None]
