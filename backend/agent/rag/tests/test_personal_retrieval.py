from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from backend.agent.rag.inference import HashingEmbeddingProvider
from backend.agent.rag.personal import (
    PersonalKnowledgeBaseIngestion,
    PersonalKnowledgeRetrievalService,
)


class _UnusedMinerU:
    configuration_fingerprint = "f" * 64

    def parse(self, _source: Path, _output_root: Path):
        raise AssertionError("TXT must use native ingestion")


class _Store:
    def get_retrieval_state(self, user_id: str) -> dict:
        if user_id != "trusted-user":
            return {
                "generation_id": None,
                "base_status": "idle",
                "collection_ready": True,
                "collection_error": None,
                "files": {},
            }
        return {
            "generation_id": "active-generation",
            "base_status": "ready",
            "collection_ready": True,
            "collection_error": None,
            "files": {"live-file": "notes.txt"},
        }


class _Index:
    dense_name = "dense"
    body_name = "bm25_body"
    heading_name = "bm25_heading"

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    def bm25_query(self, text: str) -> dict:
        return {"text": text}

    def query_points(
        self, query, using, limit, *, user_id, generation_id, file_ids
    ) -> list[dict]:
        assert query
        assert limit == 20
        self.calls.append((user_id, generation_id, tuple(file_ids)))
        return [
            {
                "chunk_id": self.payload["chunk_id"],
                "file_id": "live-file",
                "score": 1.0,
                "payload": {
                    **self.payload,
                    "scope": "personal",
                    "user_id": user_id,
                    "file_id": "live-file",
                },
            }
        ]


def test_personal_retrieval_forces_trusted_tenant_and_returns_locator(
    tmp_path: Path,
) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("Dijkstra computes shortest paths.\n", encoding="utf-8")
    ingestion = PersonalKnowledgeBaseIngestion(
        tmp_path / "artifacts", mineru_parser=_UnusedMinerU()
    )
    ingested = asyncio.run(
        ingestion.ingest(
            file_id="12345678-1234-5678-1234-567812345678",
            filename="notes.txt",
            media_type="text/plain",
            source_path=source,
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        )
    )
    chunk = ingested.chunks.chunks[0]
    index = _Index(chunk.model_dump(mode="json"))
    service = PersonalKnowledgeRetrievalService(
        store=_Store(),  # type: ignore[arg-type]
        index=index,  # type: ignore[arg-type]
        embedding=HashingEmbeddingProvider(dimensions=8),
        embedding_semaphore=asyncio.Semaphore(1),
    )

    result = asyncio.run(
        service.search(user_id="trusted-user", query="shortest paths", top_k=1)
    )

    assert result["result_count"] == 1
    assert result["results"][0]["source"] == "notes.txt"
    assert result["results"][0]["location"]["kind"] == "text_lines"
    assert index.calls == [
        ("trusted-user", "active-generation", ("live-file",)),
        ("trusted-user", "active-generation", ("live-file",)),
        ("trusted-user", "active-generation", ("live-file",)),
    ]

    other = asyncio.run(
        service.search(user_id="other-user", query="shortest paths", top_k=1)
    )
    assert other["result_count"] == 0
    assert other["degraded"] == ["personal_knowledge_base_empty"]
    assert len(index.calls) == 3
