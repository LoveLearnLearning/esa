"""Context-bound retrieval over the tenant-isolated personal collection."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from backend.agent.rag.chunk import Chunk
from backend.agent.rag.indexes import PersonalQdrantIndex
from backend.agent.rag.retrieval.context import EvidenceAssembler
from backend.agent.rag.retrieval.contracts import RankedItem
from backend.agent.rag.retrieval.fusion import reciprocal_rank_fusion
from backend.core.stores.personal_knowledge_base_store import (
    PersonalKnowledgeBaseStore,
)


class PersonalKnowledgeRetrievalService:
    """Retrieve only live files from one trusted user and active generation."""

    def __init__(
        self,
        *,
        store: PersonalKnowledgeBaseStore,
        index: PersonalQdrantIndex,
        embedding: Any,
        embedding_semaphore: asyncio.Semaphore,
        route_limit: int = 20,
    ) -> None:
        if route_limit <= 0:
            raise ValueError("personal retrieval route limit must be positive")
        self.store = store
        self.index = index
        self.embedding = embedding
        self.embedding_semaphore = embedding_semaphore
        self.route_limit = route_limit

    async def search(
        self,
        *,
        user_id: str,
        query: str,
        knowledge_base_id: str | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Return Agent-ready evidence without accepting identity from the model."""

        if not user_id:
            raise ValueError("trusted user_id is required")
        if not query.strip():
            raise ValueError("query cannot be blank")
        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")
        state = await asyncio.to_thread(
            self.store.get_retrieval_state,
            user_id,
            *(() if knowledge_base_id is None else (knowledge_base_id,)),
        )
        generation_id = state["generation_id"]
        resolved_knowledge_base_id = str(state["knowledge_base_id"])
        filenames: dict[str, str] = state["files"]
        if not state["collection_ready"]:
            return self._empty(query, "personal_collection_not_ready")
        if generation_id is None or not filenames:
            return self._empty(query, "personal_knowledge_base_empty")

        embed_query = getattr(self.embedding, "embed_query", None)
        async with self.embedding_semaphore:
            vector = await asyncio.to_thread(
                embed_query if callable(embed_query) else self._embed_query,
                query,
            )
        file_ids = tuple(filenames)
        dense, body, heading = await asyncio.gather(
            asyncio.to_thread(
                self.index.query_points,
                vector,
                self.index.dense_name,
                self.route_limit,
                user_id=user_id,
                generation_id=generation_id,
                knowledge_base_id=resolved_knowledge_base_id,
                file_ids=file_ids,
            ),
            asyncio.to_thread(
                self.index.query_points,
                self.index.bm25_query(query),
                self.index.body_name,
                self.route_limit,
                user_id=user_id,
                generation_id=generation_id,
                knowledge_base_id=resolved_knowledge_base_id,
                file_ids=file_ids,
            ),
            asyncio.to_thread(
                self.index.query_points,
                self.index.bm25_query(query),
                self.index.heading_name,
                self.route_limit,
                user_id=user_id,
                generation_id=generation_id,
                knowledge_base_id=resolved_knowledge_base_id,
                file_ids=file_ids,
            ),
        )
        routes = {"dense": dense, "bm25_body": body, "bm25_heading": heading}
        payloads = {
            item["chunk_id"]: item
            for values in routes.values()
            for item in values
        }
        ranking = reciprocal_rank_fusion(
            {
                name: [RankedItem(item["chunk_id"], item["score"]) for item in values]
                for name, values in routes.items()
            },
            rrf_k=60,
            limit=top_k,
        )
        results = []
        for rank, item in enumerate(ranking, start=1):
            raw = payloads[item.chunk_id]
            chunk_payload = {
                key: value
                for key, value in raw["payload"].items()
                if key in Chunk.model_fields
            }
            chunk = Chunk.model_validate(chunk_payload)
            filename = filenames.get(raw["file_id"])
            if filename is None:
                # SQLite is the live-file authority. A stale Qdrant payload is
                # never returned merely because it passed vector filtering.
                continue
            evidence = EvidenceAssembler.build(chunk, filename)
            primary = evidence[0]
            locator = dict(primary.locators[0]) if primary.locators else None
            results.append(
                {
                    "content": chunk.bm25_body,
                    "score": item.score,
                    "score_type": "rrf",
                    "rank": rank,
                    "source": filename,
                    "source_type": "personal",
                    "file_id": str(raw["file_id"]),
                    "knowledge_base_id": resolved_knowledge_base_id,
                    "preview_url": (
                        f"/me/knowledge-base/files/{raw['file_id']}/content"
                    ),
                    "highlight_text": primary.evidence_text,
                    "section": " / ".join(primary.section_path) or None,
                    "location": locator,
                    "chunk_id": chunk.chunk_id,
                    "evidence": [dataclasses.asdict(value) for value in evidence],
                }
            )
        return {
            "query": query,
            "result_count": len(results),
            "results": results,
            "degraded": ["personal_reranker_not_configured"],
            "rankings": {
                name: [item["chunk_id"] for item in values]
                for name, values in routes.items()
            },
        }

    def _embed_query(self, query: str) -> list[float]:
        return self.embedding.embed([query])[0]

    @staticmethod
    def _empty(query: str, reason: str) -> dict[str, Any]:
        return {
            "query": query,
            "result_count": 0,
            "results": [],
            "degraded": [reason],
            "rankings": {},
        }
