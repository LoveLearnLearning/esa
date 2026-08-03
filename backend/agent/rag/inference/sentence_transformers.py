# backend/agent/rag/inference/sentence_transformers.py

"""

这个文件干什么：Sentence Transformers Embedding 与 CrossEncoder 后端。

直白点说就是：用 Sentence Transformers 库加载真实向量模型和交叉编码重排模型。

Sentence Transformers Embedding 与 CrossEncoder 后端。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..fingerprints import configuration_sha256
from .errors import InferenceUnavailable


@dataclass
class SentenceTransformersEmbeddingProvider:
    """延迟加载的 Sentence Transformers Qwen3 Embedding 后端。"""

    model_name: str = "Qwen/Qwen3-Embedding-4B"
    device: str = "cuda"
    _model: Any = field(init=False, default=None, repr=False)

    @property
    def configuration_fingerprint(self) -> str:
        """记录影响向量内容的 Sentence Transformers 配置。"""

        return configuration_sha256(
            {
                "backend": "sentence-transformers-embedding-0.1",
                "model_name": self.model_name,
                "device": self.device,
                "normalize_embeddings": True,
            }
        )

    def _load(self) -> Any:
        """首次推理时加载 SentenceTransformer。"""

        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise InferenceUnavailable(
                    "Sentence Transformers is not installed"
                ) from exc
            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """编码并归一化一批普通文本。"""

        if not texts:
            return []
        vectors = self._load().encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vectors.tolist()

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """使用普通编码入口处理文档。"""

        return self.embed(texts)

    def embed_query(self, query: str) -> list[float]:
        """使用模型仓库提供的 query prompt 编码问题。"""

        vector = self._load().encode(
            [query],
            prompt_name="query",
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vector[0].tolist()


@dataclass
class SentenceTransformersReranker:
    """使用 Sentence Transformers CrossEncoder 执行重排。"""

    model_name: str = "Qwen/Qwen3-Reranker-4B"
    device: str = "cuda"
    _model: Any = field(init=False, default=None, repr=False)

    @property
    def configuration_fingerprint(self) -> str:
        """记录影响重排分数的 CrossEncoder 配置。"""

        return configuration_sha256(
            {
                "backend": "sentence-transformers-cross-encoder-0.1",
                "model_name": self.model_name,
                "device": self.device,
            }
        )

    def _load(self) -> Any:
        """首次推理时加载 CrossEncoder。"""

        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise InferenceUnavailable(
                    "Sentence Transformers is not installed"
                ) from exc
            self._model = CrossEncoder(self.model_name, device=self.device)
        return self._model

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        """为全部查询与文档组合批量评分。"""

        if not documents:
            return []
        values = self._load().predict(
            [(query, document) for document in documents]
        )
        return [float(value) for value in values]
