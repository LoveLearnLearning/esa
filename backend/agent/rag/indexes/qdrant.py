# backend/agent/rag/indexes/qdrant.py

"""

这个文件干什么：Qdrant 三路混合索引 REST 适配器。

直白点说就是：通过 Qdrant 接口写入和查询 Dense、正文 BM25、标题 BM25 三路索引。

Qdrant 三路混合索引 REST 适配器。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..chunk import Chunk, ContentRole
from ..fingerprints import configuration_sha256
from ..retrieval.contracts import RankedItem
from .errors import CollectionNotFound, IndexGenerationConflict, IndexUnavailable
from .unified_schema import (
    PUBLIC_SCOPE,
    UNIFIED_COLLECTION_SCHEMA_VERSION,
    UNIFIED_PAYLOAD_INDEXES,
    match_any,
    public_filter,
)


@dataclass(frozen=True)
class QdrantIndex:
    """使用一条 Dense 与两条原生 BM25 命名向量的 Qdrant 索引。"""

    base_url: str
    collection: str
    api_key: str | None = None
    timeout: float = 30.0
    dense_name: str = "dense"
    body_name: str = "bm25_body"
    heading_name: str = "bm25_heading"
    bm25_model: str = "qdrant/bm25"
    upsert_batch_size: int = 64
    generation_id: str | None = None

    def __post_init__(self) -> None:
        """完成实例初始化后的校验与派生字段构建。"""
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.upsert_batch_size <= 0:
            raise ValueError("upsert_batch_size must be positive")

    @property
    def bm25_options(self) -> dict[str, str]:
        """返回写入和查询共同使用的中文 BM25 配置。"""

        return {"tokenizer": "multilingual", "language": "none"}

    @property
    def configuration_fingerprint(self) -> str:
        """为影响索引结构的配置生成稳定指纹。"""

        return configuration_sha256(
            {
                "backend": "qdrant-rest-0.3",
                "collection_schema": UNIFIED_COLLECTION_SCHEMA_VERSION,
                "dense_name": self.dense_name,
                "body_name": self.body_name,
                "heading_name": self.heading_name,
                "bm25_model": self.bm25_model,
                "bm25_options": self.bm25_options,
            }
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """发送 Qdrant JSON 请求并统一包装传输故障。"""

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 404:
                raise CollectionNotFound(
                    f"Qdrant collection not found: {self.collection}"
                ) from exc
            raise IndexUnavailable(
                f"Qdrant request failed: {method} {path}: HTTP {exc.code}"
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise IndexUnavailable(
                f"Qdrant request failed: {method} {path}: {exc}"
            ) from exc

    def create_collection(self, dense_dimension: int) -> None:
        """Create the unified collection and every mandatory payload index."""

        if dense_dimension <= 0:
            raise ValueError("dense_dimension must be positive")
        self._request(
            "PUT",
            f"/collections/{quote(self.collection)}",
            {
                "vectors": {
                    self.dense_name: {
                        "size": dense_dimension,
                        "distance": "Cosine",
                    }
                },
                "sparse_vectors": {
                    self.body_name: {"modifier": "idf"},
                    self.heading_name: {"modifier": "idf"},
                },
            },
        )
        self.ensure_payload_indexes()

    def ensure_payload_indexes(self) -> None:
        """Create the shared filter indexes idempotently."""

        for field_name, field_schema in UNIFIED_PAYLOAD_INDEXES:
            self._request(
                "PUT",
                f"/collections/{quote(self.collection)}/index?wait=true",
                {"field_name": field_name, "field_schema": field_schema},
            )

    def prepare(
        self,
        dense_dimension: int,
        generation_id: str,
        expected_count: int,
    ) -> None:
        """创建或校验 Collection，并拒绝混入其他索引代次。"""

        if expected_count < 0:
            raise ValueError("expected_count cannot be negative")
        try:
            info = self._request(
                "GET",
                f"/collections/{quote(self.collection)}",
            )
        except CollectionNotFound:
            self.create_collection(dense_dimension)
            return
        self._validate_existing_state(
            info,
            dense_dimension,
            generation_id,
            expected_count,
        )
        self.ensure_payload_indexes()

    def validate_existing(
        self,
        dense_dimension: int,
        generation_id: str,
        expected_count: int,
    ) -> None:
        """只读校验已有 Collection 的配置、代次和完整数量。"""

        info = self._request(
            "GET",
            f"/collections/{quote(self.collection)}",
        )
        self._validate_existing_state(
            info,
            dense_dimension,
            generation_id,
            expected_count,
        )
        if not self.generation_is_ready(generation_id, expected_count):
            raise IndexUnavailable("Qdrant index generation is incomplete")

    def _validate_existing_state(
        self,
        info: dict[str, Any],
        dense_dimension: int,
        generation_id: str,
        expected_count: int,
    ) -> None:
        """校验 Collection 配置并拒绝其他或过量代次。"""

        self._validate_collection(info, dense_dimension)
        total_count = self._count_public()
        generation_count = self._count(generation_id)
        if total_count != generation_count:
            raise IndexGenerationConflict(
                "Qdrant public scope contains points from another index generation"
            )
        if total_count > expected_count:
            raise IndexGenerationConflict(
                "Qdrant public scope contains more points than the expected generation"
            )

    def generation_is_ready(
        self,
        generation_id: str,
        expected_count: int,
    ) -> bool:
        """确认 Collection 只包含指定代次且 Point 数量完整。"""

        return (
            self._count_public() == expected_count
            and self._count(generation_id) == expected_count
        )

    def _count_public(self) -> int:
        """Count public points without inspecting personal tenant data."""

        response = self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/count",
            {"exact": True, "filter": public_filter(visible=None)},
        )
        try:
            return int(response["result"]["count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IndexUnavailable("Qdrant public count response is incomplete") from exc

    def _validate_collection(
        self,
        response: dict[str, Any],
        dense_dimension: int,
    ) -> None:
        """校验已有 Collection 的 Dense 维度和命名向量集合。"""

        try:
            parameters = response["result"]["config"]["params"]
            vectors = parameters["vectors"]
            sparse_vectors = parameters["sparse_vectors"]
            dense = vectors[self.dense_name]
        except (KeyError, TypeError) as exc:
            raise IndexUnavailable(
                "Qdrant collection response is missing vector configuration"
            ) from exc
        try:
            actual_dimension = int(dense["size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IndexUnavailable(
                "Qdrant collection response is missing dense vector size"
            ) from exc
        if actual_dimension != dense_dimension:
            raise IndexGenerationConflict(
                "Qdrant dense vector dimension does not match the embedding output"
            )
        if set(vectors) != {self.dense_name}:
            raise IndexGenerationConflict(
                "Qdrant dense vector names do not match the RAG configuration"
            )
        if set(sparse_vectors) != {self.body_name, self.heading_name}:
            raise IndexGenerationConflict(
                "Qdrant sparse vector names do not match the RAG configuration"
            )

    def _count(self, generation_id: str | None = None) -> int:
        """精确统计全部 Point 或指定索引代次的 Point。"""

        payload: dict[str, Any] = {
            "exact": True,
            "filter": public_filter(generation_id=generation_id, visible=None),
        }
        response = self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/count",
            payload,
        )
        try:
            return int(response["result"]["count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IndexUnavailable("Qdrant count response is incomplete") from exc

    def build(
        self,
        chunks: Sequence[Chunk],
        dense_vectors: Sequence[Sequence[float]],
        *,
        generation_id: str,
    ) -> None:
        """把 Chunk 的三种表示写入同一个可复现 Point。"""

        if len(chunks) != len(dense_vectors):
            raise ValueError("one dense vector is required for every chunk")
        points = [
            self._point(chunk, dense_vector, generation_id)
            for chunk, dense_vector in zip(chunks, dense_vectors)
        ]
        for start in range(0, len(points), self.upsert_batch_size):
            self._request(
                "PUT",
                f"/collections/{quote(self.collection)}/points?wait=true",
                {"points": points[start : start + self.upsert_batch_size]},
            )

    def _point(
        self,
        chunk: Chunk,
        dense_vector: Sequence[float],
        generation_id: str,
    ) -> dict[str, Any]:
        """把一个 Chunk 转换为 Qdrant Point。"""

        payload = chunk.model_dump(mode="json")
        payload.update(
            {
                "scope": PUBLIC_SCOPE,
                "index_generation_id": generation_id,
                "visible": True,
            }
        )
        return {
            "id": str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"public://{generation_id}/{chunk.chunk_id}",
                )
            ),
            "vector": {
                self.dense_name: list(dense_vector),
                self.body_name: self._bm25_document(chunk.bm25_body),
                self.heading_name: self._bm25_document(chunk.bm25_heading),
            },
            "payload": payload,
        }

    def _bm25_document(self, text: str) -> dict[str, Any]:
        """构造写入和查询共用的 Qdrant BM25 文档。"""

        return {
            "text": text,
            "model": self.bm25_model,
            "options": self.bm25_options,
        }

    def _query(
        self,
        query: Any,
        using: str,
        limit: int,
        content_roles: frozenset[ContentRole] | None = None,
    ) -> list[RankedItem]:
        """查询一条命名向量并转换为领域排名项。"""

        payload: dict[str, Any] = {
            "query": query,
            "using": using,
            "limit": limit,
            # Ranking only needs the stable domain identifier.  Evidence and
            # retrieval text are resolved from the already loaded collection,
            # so transferring the complete Chunk payload wastes bandwidth.
            "with_payload": {"include": ["chunk_id"]},
            "filter": public_filter(generation_id=self.generation_id),
        }
        if content_roles is not None:
            payload["filter"]["must"].append(
                match_any(
                    "content_role",
                    sorted(role.value for role in content_roles),
                )
            )
        response = self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/query",
            payload,
        )
        result = response.get("result", {})
        points = result.get("points", result if isinstance(result, list) else [])
        try:
            return [
                RankedItem(str(point["payload"]["chunk_id"]), float(point["score"]))
                for point in points
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise IndexUnavailable("Qdrant query response is incomplete") from exc

    def dense(
        self,
        query_vector: Sequence[float],
        limit: int,
        content_roles: frozenset[ContentRole] | None = None,
    ) -> list[RankedItem]:
        """通过 Dense 命名向量执行语义召回。"""

        return self._query(list(query_vector), self.dense_name, limit, content_roles)

    def bm25_body(
        self,
        query: str,
        limit: int,
        content_roles: frozenset[ContentRole] | None = None,
    ) -> list[RankedItem]:
        """通过正文 BM25 命名向量执行召回。"""

        return self._query(
            self._bm25_document(query), self.body_name, limit, content_roles
        )

    def bm25_heading(
        self,
        query: str,
        limit: int,
        content_roles: frozenset[ContentRole] | None = None,
    ) -> list[RankedItem]:
        """通过标题 BM25 命名向量执行召回。"""

        return self._query(
            self._bm25_document(query), self.heading_name, limit, content_roles
        )
