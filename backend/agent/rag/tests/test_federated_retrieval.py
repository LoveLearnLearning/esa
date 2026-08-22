"""Tests for the combined personal and public knowledge retrieval contract."""

from __future__ import annotations

import asyncio

from backend.agent.rag.federated import retrieve_federated_knowledge_payload


def _item(scope: str, rank: int) -> dict:
    return {
        "content": f"{scope} evidence {rank}",
        "score": 0.9 / rank,
        "score_type": "local",
        "rank": rank,
        "source": f"{scope}.md",
        "section": f"section {rank}",
        "chunk_id": f"{scope}-{rank}",
        "evidence": [],
    }


class _PersonalRetrieval:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def search(self, *, user_id: str, query: str, top_k: int) -> dict:
        self.calls.append({"user_id": user_id, "query": query, "top_k": top_k})
        return {
            "query": query,
            "result_count": 2,
            "results": [_item("personal", 1), _item("personal", 2)],
            "degraded": ["personal_reranker_not_configured"],
            "rankings": {},
        }


def test_federated_retrieval_queries_both_scopes_and_balances_results(
    monkeypatch,
) -> None:
    public_calls = []

    def public_retrieve(
        query,
        top_k=5,
        similarity_threshold=None,
        service=None,
    ):
        public_calls.append(
            {
                "query": query,
                "top_k": top_k,
                "similarity_threshold": similarity_threshold,
                "service": service,
            }
        )
        return {
            "query": query,
            "result_count": 2,
            "results": [_item("public", 1), _item("public", 2)],
            "degraded": [],
            "rankings": {},
        }

    monkeypatch.setattr(
        "backend.agent.rag.federated.retrieve_knowledge_payload",
        public_retrieve,
    )
    personal = _PersonalRetrieval()
    public_service = object()

    result = asyncio.run(
        retrieve_federated_knowledge_payload(
            user_id="trusted-user",
            query="Rust lifetimes",
            top_k=4,
            public_service=public_service,
            personal_service=personal,
        )
    )

    assert [item["knowledge_scope"] for item in result["results"]] == [
        "personal",
        "public",
        "personal",
        "public",
    ]
    assert result["federation"] == {
        "mode": "personal_and_public",
        "personal_candidates": 2,
        "public_candidates": 2,
    }
    assert "个人知识库" in result["sources"][0]
    assert "公共知识库" in result["sources"][1]
    assert personal.calls == [
        {"user_id": "trusted-user", "query": "Rust lifetimes", "top_k": 8}
    ]
    assert public_calls == [
        {
            "query": "Rust lifetimes",
            "top_k": 8,
            "similarity_threshold": None,
            "service": public_service,
        }
    ]


def test_federated_retrieval_keeps_personal_results_when_public_fails(
    monkeypatch,
) -> None:
    def public_retrieve(*_args, **_kwargs):
        raise RuntimeError("public backend unavailable")

    monkeypatch.setattr(
        "backend.agent.rag.federated.retrieve_knowledge_payload",
        public_retrieve,
    )

    result = asyncio.run(
        retrieve_federated_knowledge_payload(
            user_id="trusted-user",
            query="Rust lifetimes",
            top_k=2,
            personal_service=_PersonalRetrieval(),
        )
    )

    assert result["result_count"] == 2
    assert all(
        item["knowledge_scope"] == "personal" for item in result["results"]
    )
    assert "public:public_retrieval_failed" in result["degraded"]
