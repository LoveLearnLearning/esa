# backend/agent/rag/indexes/reference.py

"""

这个文件干什么：不依赖外部服务的确定性参考索引。

直白点说就是：用纯 Python 做一个小型可重复索引，没启动 Qdrant 或真实模型时也能开发和测试。

不依赖外部服务的确定性参考索引。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from ..chunk import Chunk, ContentRole
from ..fingerprints import configuration_sha256
from ..retrieval.contracts import RankedItem


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """计算两个等维向量的余弦相似度。"""

    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    denominator = left_norm * right_norm
    return dot / denominator if denominator else 0.0


_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u3400-\u9fff]")


def reference_tokens(text: str) -> list[str]:
    """执行确定性测试分词，不宣称等价于生产中文分词器。"""

    base = _TOKEN_RE.findall(text.lower())
    cjk = [token for token in base if len(token) == 1 and "\u3400" <= token <= "\u9fff"]
    bigrams = ["".join(cjk[index : index + 2]) for index in range(len(cjk) - 1)]
    return base + bigrams


@dataclass
class ReferenceIndex:
    """小规模确定性回归后端，不能替代生产索引。"""

    chunks: list[Chunk] = field(default_factory=list)
    vectors: list[list[float]] = field(default_factory=list)
    generation_id: str | None = None

    @property
    def configuration_fingerprint(self) -> str:
        """返回参考 BM25 与 Dense 实现的稳定配置指纹。"""

        return configuration_sha256(
            {
                "backend": "reference-index-0.2",
                "bm25": {"k1": 1.2, "b": 0.75},
                "tokenizer": "reference-tokenizer-0.1",
            }
        )

    def prepare(
        self,
        dense_dimension: int,
        generation_id: str,
        expected_count: int,
    ) -> None:
        """校验参考索引准备参数。"""

        if dense_dimension <= 0:
            raise ValueError("dense_dimension must be positive")
        if not generation_id:
            raise ValueError("generation_id cannot be blank")
        if expected_count < 0:
            raise ValueError("expected_count cannot be negative")

    def generation_is_ready(
        self,
        generation_id: str,
        expected_count: int,
    ) -> bool:
        """确认内存索引的代次和数量完整。"""

        return (
            self.generation_id == generation_id
            and len(self.chunks) == expected_count
            and len(self.vectors) == expected_count
        )

    def build(
        self,
        chunks: Sequence[Chunk],
        dense_vectors: Sequence[Sequence[float]],
        *,
        generation_id: str,
    ) -> None:
        """校验向量矩阵后，在内存中保存完整索引。"""

        if len(chunks) != len(dense_vectors):
            raise ValueError("one dense vector is required for every chunk")
        dimensions = {len(vector) for vector in dense_vectors}
        if not dimensions or len(dimensions) != 1 or 0 in dimensions:
            raise ValueError("dense vectors must have one non-zero dimension")
        self.chunks = list(chunks)
        self.vectors = [list(vector) for vector in dense_vectors]
        self.generation_id = generation_id

    def dense(
        self,
        query_vector: Sequence[float],
        limit: int,
        content_roles: frozenset[ContentRole] | None = None,
    ) -> list[RankedItem]:
        """按余弦相似度执行参考 Dense 召回。"""

        if self.vectors and len(query_vector) != len(self.vectors[0]):
            raise ValueError("query vector dimension does not match index")
        ranked = [
            RankedItem(chunk.chunk_id, _cosine(query_vector, vector))
            for chunk, vector in zip(self.chunks, self.vectors)
            if content_roles is None or chunk.content_role in content_roles
        ]
        return sorted(ranked, key=lambda item: (-item.score, item.chunk_id))[:limit]

    def _bm25(
        self,
        query: str,
        field_name: str,
        limit: int,
        content_roles: frozenset[ContentRole] | None,
    ) -> list[RankedItem]:
        """在一个 Chunk 文本字段上计算参考 BM25。"""

        selected = [
            chunk
            for chunk in self.chunks
            if content_roles is None or chunk.content_role in content_roles
        ]
        documents = [reference_tokens(getattr(chunk, field_name)) for chunk in selected]
        query_tokens = reference_tokens(query)
        average_length = sum(map(len, documents)) / len(documents) if documents else 0.0
        frequencies = Counter(
            token for document in documents for token in set(document)
        )
        ranked: list[RankedItem] = []
        for chunk, document in zip(selected, documents):
            counts = Counter(document)
            score = self._bm25_score(
                query_tokens,
                counts,
                frequencies,
                len(document),
                average_length,
                len(documents),
            )
            if score > 0:
                ranked.append(RankedItem(chunk.chunk_id, score))
        return sorted(ranked, key=lambda item: (-item.score, item.chunk_id))[:limit]

    @staticmethod
    def _bm25_score(
        query_tokens: Sequence[str],
        counts: Counter[str],
        document_frequencies: Counter[str],
        document_length: int,
        average_length: float,
        document_count: int,
    ) -> float:
        """计算一个文档对查询的参考 BM25 分数。"""

        score = 0.0
        for token in query_tokens:
            frequency = counts[token]
            if not frequency:
                continue
            document_frequency = document_frequencies[token]
            inverse_document_frequency = math.log(
                1.0
                + (document_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            normalization = frequency + 1.2 * (
                1.0 - 0.75 + 0.75 * document_length / (average_length or 1.0)
            )
            score += inverse_document_frequency * frequency * 2.2 / normalization
        return score

    def bm25_body(
        self,
        query: str,
        limit: int,
        content_roles: frozenset[ContentRole] | None = None,
    ) -> list[RankedItem]:
        """对正文执行参考 BM25 召回。"""

        return self._bm25(query, "bm25_body", limit, content_roles)

    def bm25_heading(
        self,
        query: str,
        limit: int,
        content_roles: frozenset[ContentRole] | None = None,
    ) -> list[RankedItem]:
        """对标题与章节路径执行参考 BM25 召回。"""

        return self._bm25(query, "bm25_heading", limit, content_roles)
