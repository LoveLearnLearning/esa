# backend/agent/rag/inference/reference.py

"""

这个文件干什么：不依赖模型的确定性参考 Embedding 与 Reranker。

直白点说就是：不用下载真实模型，靠固定哈希和词语重叠提供可重复的替代结果，方便测试整条流程。

不依赖模型的确定性参考 Embedding 与 Reranker。
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from ..fingerprints import configuration_sha256
from ..indexes import reference_tokens


@dataclass(frozen=True)
class HashingEmbeddingProvider:
    """用稳定 token 哈希验证 Dense 数据流，不模拟语义理解。"""

    dimensions: int = 384
    model_name: str = "reference-hashing-embedding-0.1"

    def __post_init__(self) -> None:
        if self.dimensions <= 0:
            raise ValueError("dimensions must be positive")

    @property
    def configuration_fingerprint(self) -> str:
        return configuration_sha256(
            {"model_name": self.model_name, "dimensions": self.dimensions}
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            counts = Counter(reference_tokens(text))
            vector = [0.0] * self.dimensions
            for token, frequency in counts.items():
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                position = int.from_bytes(digest[:8], "big") % self.dimensions
                sign = 1.0 if digest[8] & 1 else -1.0
                vector[position] += sign * (1.0 + math.log(frequency))
            norm = math.sqrt(sum(value * value for value in vector))
            if norm:
                vector = [value / norm for value in vector]
            vectors.append(vector)
        return vectors

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self.embed(texts)

    def embed_query(self, query: str) -> list[float]:
        return self.embed([query])[0]


@dataclass(frozen=True)
class LexicalOverlapReranker:
    """以确定性 token 加权 Jaccard 验证重排数据流。"""

    model_name: str = "reference-lexical-overlap-reranker-0.1"

    @property
    def configuration_fingerprint(self) -> str:
        return configuration_sha256(
            {"model_name": self.model_name, "score": "weighted-jaccard"}
        )

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        query_counts = Counter(reference_tokens(query))
        output: list[float] = []
        for document in documents:
            document_counts = Counter(reference_tokens(document))
            tokens = set(query_counts) | set(document_counts)
            numerator = sum(
                min(query_counts[token], document_counts[token]) for token in tokens
            )
            denominator = sum(
                max(query_counts[token], document_counts[token]) for token in tokens
            )
            output.append(numerator / denominator if denominator else 0.0)
        return output
