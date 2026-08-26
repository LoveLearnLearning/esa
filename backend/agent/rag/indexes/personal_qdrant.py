"""Tenant-enforcing Qdrant adapter for personal knowledge bases."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from ..chunk import Chunk, ContentRole
from ..fingerprints import configuration_sha256
from ..retrieval.contracts import RankedItem
from .errors import CollectionNotFound, IndexGenerationConflict, IndexUnavailable
from .qdrant import QdrantIndex
from .unified_schema import (
    PERSONAL_SCOPE,
    UNIFIED_COLLECTION_SCHEMA_VERSION,
    UNIFIED_PAYLOAD_INDEXES,
    public_filter,
)


@dataclass(frozen=True)
class PersonalQdrantIndex:
    """A personal-only collection API with no unscoped query/delete methods."""

    base_url: str
    collection: str
    api_key: str | None = None
    timeout: float = 30.0
    dense_name: str = "dense"
    body_name: str = "bm25_body"
    heading_name: str = "bm25_heading"
    bm25_model: str = "qdrant/bm25"
    upsert_batch_size: int = 64

    def __post_init__(self) -> None:
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.upsert_batch_size <= 0:
            raise ValueError("upsert_batch_size must be positive")

    @property
    def configuration_fingerprint(self) -> str:
        return configuration_sha256(
            {
                "backend": "personal-qdrant-rest-0.2",
                "collection_schema": UNIFIED_COLLECTION_SCHEMA_VERSION,
                "dense_name": self.dense_name,
                "body_name": self.body_name,
                "heading_name": self.heading_name,
                "bm25_model": self.bm25_model,
                "bm25_options": self.bm25_options,
                "tenant_payload": [
                    "scope",
                    "user_id",
                    "knowledge_base_id",
                    "file_id",
                    "kb_generation_id",
                    "ingestion_revision",
                    "visible",
                ],
            }
        )

    @property
    def bm25_options(self) -> dict[str, str]:
        return {"tokenizer": "multilingual", "language": "none"}

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = QdrantIndex(
            base_url=self.base_url,
            collection=self.collection,
            api_key=self.api_key,
            timeout=self.timeout,
            dense_name=self.dense_name,
            body_name=self.body_name,
            heading_name=self.heading_name,
            bm25_model=self.bm25_model,
            upsert_batch_size=self.upsert_batch_size,
        )
        return client._request(method, path, payload)

    def create_collection(self, dense_dimension: int) -> None:
        """Create the unified collection and every shared payload index."""

        if dense_dimension <= 0:
            raise ValueError("dense_dimension must be positive")
        self._request(
            "PUT",
            f"/collections/{quote(self.collection)}",
            {
                "vectors": {
                    self.dense_name: {"size": dense_dimension, "distance": "Cosine"}
                },
                "sparse_vectors": {
                    self.body_name: {"modifier": "idf"},
                    self.heading_name: {"modifier": "idf"},
                },
            },
        )
        for field_name, field_schema in UNIFIED_PAYLOAD_INDEXES:
            self._request(
                "PUT",
                f"/collections/{quote(self.collection)}/index?wait=true",
                {"field_name": field_name, "field_schema": field_schema},
            )

    def ensure_collection(self, dense_dimension: int) -> None:
        """Create once or validate the existing named-vector configuration."""

        try:
            response = self._request(
                "GET", f"/collections/{quote(self.collection)}"
            )
        except CollectionNotFound:
            self.create_collection(dense_dimension)
            return
        try:
            params = response["result"]["config"]["params"]
            vectors = params["vectors"]
            sparse = params["sparse_vectors"]
            actual_dimension = int(vectors[self.dense_name]["size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IndexUnavailable(
                "personal Qdrant collection configuration is incomplete"
            ) from exc
        if actual_dimension != dense_dimension:
            raise IndexGenerationConflict(
                "personal Qdrant dense dimension does not match embedding"
            )
        if set(vectors) != {self.dense_name} or set(sparse) != {
            self.body_name,
            self.heading_name,
        }:
            raise IndexGenerationConflict(
                "personal Qdrant named vectors do not match configuration"
            )
        for field_name, field_schema in UNIFIED_PAYLOAD_INDEXES:
            self._request(
                "PUT",
                f"/collections/{quote(self.collection)}/index?wait=true",
                {"field_name": field_name, "field_schema": field_schema},
            )

    def maintenance_count_all(self) -> int:
        """Count every scope for whole unified-collection snapshot metadata.

        This deliberately maintenance-only operation is not used by retrieval
        or tenant mutation code; those paths must use :meth:`count`.
        """

        response = self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/count",
            {"exact": True},
        )
        try:
            return int(response["result"]["count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IndexUnavailable(
                "personal Qdrant maintenance count response is incomplete"
            ) from exc

    def maintenance_count_personal(self) -> int:
        """Count only personal points in the shared collection."""

        response = self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/count",
            {
                "exact": True,
                "filter": {
                    "must": [
                        {"key": "scope", "match": {"value": PERSONAL_SCOPE}}
                    ]
                },
            },
        )
        try:
            return int(response["result"]["count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IndexUnavailable(
                "personal Qdrant scope count response is incomplete"
            ) from exc

    def maintenance_count_public(self, generation_id: str | None = None) -> int:
        """Count the public scope, optionally bound to one deployment generation."""

        response = self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/count",
            {
                "exact": True,
                "filter": public_filter(
                    generation_id=generation_id,
                    visible=None,
                ),
            },
        )
        try:
            return int(response["result"]["count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IndexUnavailable(
                "unified Qdrant public count response is incomplete"
            ) from exc

    def maintenance_delete_personal_scope(self) -> None:
        """Delete personal points while preserving the public scope."""

        self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/delete?wait=true",
            {
                "filter": {
                    "must": [
                        {"key": "scope", "match": {"value": PERSONAL_SCOPE}}
                    ]
                }
            },
        )

    def maintenance_recreate_collection(self, dense_dimension: int) -> None:
        """Replace only the configured derived personal collection."""

        try:
            self._request(
                "DELETE",
                f"/collections/{quote(self.collection)}?timeout={self.timeout}",
            )
        except CollectionNotFound:
            pass
        self.create_collection(dense_dimension)

    def maintenance_delete_collection(self) -> None:
        """Delete exactly this adapter's configured maintenance collection."""

        try:
            self._request(
                "DELETE",
                f"/collections/{quote(self.collection)}?timeout={self.timeout}",
            )
        except CollectionNotFound:
            pass

    def maintenance_file_absent(self, *, user_id: str, file_id: str) -> bool:
        """Verify a restored snapshot has no point for one deleted tenant file."""

        if not user_id or not file_id:
            raise ValueError("maintenance tenant identity cannot be blank")
        tenant_file_filter = {
            "must": [
                {"key": "scope", "match": {"value": PERSONAL_SCOPE}},
                {"key": "user_id", "match": {"value": user_id}},
                {"key": "file_id", "match": {"value": file_id}},
            ]
        }
        counted = self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/count",
            {"exact": True, "filter": tenant_file_filter},
        )
        scrolled = self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/scroll",
            {
                "limit": 1,
                "with_payload": False,
                "with_vector": False,
                "filter": tenant_file_filter,
            },
        )
        try:
            count = int(counted["result"]["count"])
            result = scrolled["result"]
            points = result.get("points", result) if isinstance(result, dict) else result
            return count == 0 and isinstance(points, list) and not points
        except (KeyError, TypeError, ValueError) as exc:
            raise IndexUnavailable(
                "personal snapshot privacy verification response is incomplete"
            ) from exc

    def maintenance_delete_user(self, *, user_id: str) -> None:
        """Delete every personal point for one trusted tenant identity."""

        self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/delete?wait=true",
            {"filter": self._maintenance_user_filter(user_id)},
        )

    def maintenance_user_absent(self, *, user_id: str) -> bool:
        """Prove count and scroll both find no point for a deleted tenant."""

        tenant_filter = self._maintenance_user_filter(user_id)
        counted = self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/count",
            {"exact": True, "filter": tenant_filter},
        )
        scrolled = self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/scroll",
            {
                "limit": 1,
                "with_payload": False,
                "with_vector": False,
                "filter": tenant_filter,
            },
        )
        try:
            count = int(counted["result"]["count"])
            result = scrolled["result"]
            points = result.get("points", result) if isinstance(result, dict) else result
            return count == 0 and isinstance(points, list) and not points
        except (KeyError, TypeError, ValueError) as exc:
            raise IndexUnavailable(
                "personal user purge verification response is incomplete"
            ) from exc

    @staticmethod
    def _maintenance_user_filter(user_id: str) -> dict[str, Any]:
        if not user_id:
            raise ValueError("maintenance tenant identity cannot be blank")
        return {
            "must": [
                {"key": "scope", "match": {"value": "personal"}},
                {"key": "user_id", "match": {"value": user_id}},
            ]
        }

    @staticmethod
    def tenant_filter(
        *,
        user_id: str,
        generation_id: str,
        knowledge_base_id: str | None = None,
        visible: bool | None = True,
        file_id: str | None = None,
        file_ids: Sequence[str] | None = None,
        content_roles: frozenset[ContentRole] | None = None,
    ) -> dict[str, Any]:
        """Build the sole filter used by query, count, hide, verify and delete."""

        if not user_id or not generation_id:
            raise ValueError("user_id and generation_id are required")
        must: list[dict[str, Any]] = [
            {"key": "scope", "match": {"value": PERSONAL_SCOPE}},
            {"key": "user_id", "match": {"value": user_id}},
            {"key": "kb_generation_id", "match": {"value": generation_id}},
        ]
        if knowledge_base_id is not None:
            if not knowledge_base_id:
                raise ValueError("knowledge_base_id cannot be blank")
            must.append(
                {
                    "key": "knowledge_base_id",
                    "match": {"value": knowledge_base_id},
                }
            )
        if visible is not None:
            must.append({"key": "visible", "match": {"value": visible}})
        if file_id is not None:
            if not file_id:
                raise ValueError("file_id cannot be blank")
            must.append({"key": "file_id", "match": {"value": file_id}})
        if file_ids is not None:
            allowed = sorted({value for value in file_ids if value})
            if not allowed:
                raise ValueError("file_ids cannot be empty")
            must.append({"key": "file_id", "match": {"any": allowed}})
        if content_roles is not None:
            must.append(
                {
                    "key": "content_role",
                    "match": {"any": sorted(role.value for role in content_roles)},
                }
            )
        return {"must": must}

    def _bm25_document(self, text: str) -> dict[str, Any]:
        return {
            "text": text,
            "model": self.bm25_model,
            "options": self.bm25_options,
        }

    def bm25_query(self, text: str) -> dict[str, Any]:
        """Build the configured sparse query without exposing internals."""

        if not text.strip():
            raise ValueError("BM25 query cannot be blank")
        return self._bm25_document(text)

    def _point(
        self,
        chunk: Chunk,
        dense_vector: Sequence[float],
        *,
        user_id: str,
        knowledge_base_id: str,
        file_id: str,
        generation_id: str,
        ingestion_revision: int,
    ) -> dict[str, Any]:
        if not user_id or not knowledge_base_id or not file_id or not generation_id:
            raise ValueError("tenant point identity cannot be blank")
        if ingestion_revision <= 0:
            raise ValueError("ingestion_revision must be positive")
        payload = chunk.model_dump(mode="json")
        payload.update(
            {
                "scope": PERSONAL_SCOPE,
                "user_id": user_id,
                "knowledge_base_id": knowledge_base_id,
                "file_id": file_id,
                "kb_generation_id": generation_id,
                "ingestion_revision": ingestion_revision,
                "visible": False,
            }
        )
        identity = (
            f"personal://{user_id}/{knowledge_base_id}/"
            f"{generation_id}/{chunk.chunk_id}"
        )
        return {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, identity)),
            "vector": {
                self.dense_name: list(dense_vector),
                self.body_name: self._bm25_document(chunk.bm25_body),
                self.heading_name: self._bm25_document(chunk.bm25_heading),
            },
            "payload": payload,
        }

    def upsert_hidden(
        self,
        chunks: Sequence[Chunk],
        dense_vectors: Sequence[Sequence[float]],
        *,
        user_id: str,
        knowledge_base_id: str,
        file_id: str,
        generation_id: str,
        ingestion_revision: int,
    ) -> None:
        if len(chunks) != len(dense_vectors):
            raise ValueError("one dense vector is required for every chunk")
        points = [
            self._point(
                chunk,
                vector,
                user_id=user_id,
                knowledge_base_id=knowledge_base_id,
                file_id=file_id,
                generation_id=generation_id,
                ingestion_revision=ingestion_revision,
            )
            for chunk, vector in zip(chunks, dense_vectors)
        ]
        for start in range(0, len(points), self.upsert_batch_size):
            self._request(
                "PUT",
                f"/collections/{quote(self.collection)}/points?wait=true",
                {"points": points[start : start + self.upsert_batch_size]},
            )

    def count(
        self,
        *,
        user_id: str,
        generation_id: str,
        knowledge_base_id: str | None = None,
        file_id: str | None = None,
        visible: bool | None = True,
    ) -> int:
        response = self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/count",
            {
                "exact": True,
                "filter": self.tenant_filter(
                    user_id=user_id,
                    generation_id=generation_id,
                    knowledge_base_id=knowledge_base_id,
                    file_id=file_id,
                    visible=visible,
                ),
            },
        )
        try:
            return int(response["result"]["count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IndexUnavailable("Qdrant count response is incomplete") from exc

    def set_file_visibility(
        self,
        *,
        user_id: str,
        file_id: str,
        generation_id: str,
        knowledge_base_id: str | None = None,
        visible: bool,
    ) -> None:
        self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/payload?wait=true",
            {
                "payload": {"visible": visible},
                "filter": self.tenant_filter(
                    user_id=user_id,
                    generation_id=generation_id,
                    knowledge_base_id=knowledge_base_id,
                    file_id=file_id,
                    visible=None,
                ),
            },
        )

    def delete_file(
        self,
        *,
        user_id: str,
        file_id: str,
        generation_id: str,
        knowledge_base_id: str | None = None,
    ) -> None:
        self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/delete?wait=true",
            {
                "filter": self.tenant_filter(
                    user_id=user_id,
                    generation_id=generation_id,
                    knowledge_base_id=knowledge_base_id,
                    file_id=file_id,
                    visible=None,
                )
            },
        )

    def delete_generation(
        self,
        *,
        user_id: str,
        knowledge_base_id: str,
        generation_id: str,
    ) -> None:
        self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/delete?wait=true",
            {
                "filter": self.tenant_filter(
                    user_id=user_id,
                    generation_id=generation_id,
                    knowledge_base_id=knowledge_base_id,
                    visible=None,
                )
            },
        )

    def _query(
        self,
        query: Any,
        using: str,
        limit: int,
        *,
        user_id: str,
        generation_id: str,
        knowledge_base_id: str | None = None,
        content_roles: frozenset[ContentRole] | None = None,
        file_ids: Sequence[str] | None = None,
    ) -> list[RankedItem]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        response = self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/query",
            {
                "query": query,
                "using": using,
                "limit": limit,
                "with_payload": True,
                "filter": self.tenant_filter(
                    user_id=user_id,
                    generation_id=generation_id,
                    knowledge_base_id=knowledge_base_id,
                    content_roles=content_roles,
                    file_ids=file_ids,
                ),
            },
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
        *,
        user_id: str,
        generation_id: str,
        knowledge_base_id: str | None = None,
        content_roles: frozenset[ContentRole] | None = None,
        file_ids: Sequence[str] | None = None,
    ) -> list[RankedItem]:
        return self._query(
            list(query_vector), self.dense_name, limit,
            user_id=user_id, generation_id=generation_id,
            knowledge_base_id=knowledge_base_id,
            content_roles=content_roles,
            file_ids=file_ids,
        )

    def bm25_body(
        self,
        query: str,
        limit: int,
        *,
        user_id: str,
        generation_id: str,
        knowledge_base_id: str | None = None,
        content_roles: frozenset[ContentRole] | None = None,
        file_ids: Sequence[str] | None = None,
    ) -> list[RankedItem]:
        return self._query(
            self._bm25_document(query), self.body_name, limit,
            user_id=user_id, generation_id=generation_id,
            knowledge_base_id=knowledge_base_id,
            content_roles=content_roles,
            file_ids=file_ids,
        )

    def bm25_heading(
        self,
        query: str,
        limit: int,
        *,
        user_id: str,
        generation_id: str,
        knowledge_base_id: str | None = None,
        content_roles: frozenset[ContentRole] | None = None,
        file_ids: Sequence[str] | None = None,
    ) -> list[RankedItem]:
        return self._query(
            self._bm25_document(query), self.heading_name, limit,
            user_id=user_id, generation_id=generation_id,
            knowledge_base_id=knowledge_base_id,
            content_roles=content_roles,
            file_ids=file_ids,
        )

    def query_points(
        self,
        query: Any,
        using: str,
        limit: int,
        *,
        user_id: str,
        generation_id: str,
        knowledge_base_id: str,
        file_ids: Sequence[str],
    ) -> list[dict[str, Any]]:
        """Return tenant-filtered payloads for personal evidence assembly."""

        if using not in {self.dense_name, self.body_name, self.heading_name}:
            raise ValueError("unknown personal query vector")
        if limit <= 0:
            raise ValueError("limit must be positive")
        response = self._request(
            "POST",
            f"/collections/{quote(self.collection)}/points/query",
            {
                "query": query,
                "using": using,
                "limit": limit,
                "with_payload": True,
                "filter": self.tenant_filter(
                    user_id=user_id,
                    generation_id=generation_id,
                    knowledge_base_id=knowledge_base_id,
                    file_ids=file_ids,
                ),
            },
        )
        result = response.get("result", {})
        points = result.get("points", result if isinstance(result, list) else [])
        try:
            return [
                {
                    "chunk_id": str(point["payload"]["chunk_id"]),
                    "file_id": str(point["payload"]["file_id"]),
                    "score": float(point["score"]),
                    "payload": dict(point["payload"]),
                }
                for point in points
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise IndexUnavailable(
                "personal Qdrant evidence query response is incomplete"
            ) from exc
