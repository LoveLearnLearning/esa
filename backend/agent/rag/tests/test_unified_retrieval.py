"""Agent-facing federation tests for the unified knowledge tool."""

from __future__ import annotations

import asyncio
import json

from backend.agent.rag import unified_retrieval
from backend.core.utils.models import ToolExecutionResult


def _public_result() -> ToolExecutionResult:
    return ToolExecutionResult(
        model_content={
            "results": [
                {
                    "chunk_id": "pub-1",
                    "content": "public first",
                    "source_ref": "public-evidence-1",
                    "quote_eligible": True,
                    "citation_mode": "verbatim_allowed",
                },
                {
                    "chunk_id": "pub-2",
                    "content": "public second",
                    "source_ref": "public-evidence-2",
                    "quote_eligible": False,
                    "citation_mode": "paraphrase_only_unverified",
                },
            ],
            "execution": {"degraded": ["public_degraded"]},
        },
        display_content={
            "results": [
                {"rank": 1, "chunk_id": "pub-1", "source": "Public.pdf"},
                {"rank": 2, "chunk_id": "pub-2", "source": "Public.pdf"},
            ]
        },
        audit_metadata={"response": "full-public"},
    )


class _PersonalService:
    def __init__(self) -> None:
        self.arguments = None

    async def search(self, **arguments):
        self.arguments = arguments
        return {
            "query": arguments["query"],
            "result_count": 2,
            "results": [
                {
                    "chunk_id": "per-1",
                    "content": "personal first",
                    "source": "Notes.txt",
                    "section": "One",
                    "location": {"page": 3},
                    "evidence": [
                        {"evidence_id": "personal-evidence-1", "quote_eligible": True}
                    ],
                },
                {
                    "chunk_id": "per-2",
                    "content": "personal second",
                    "source": "Notes.txt",
                    "section": "Two",
                    "location": None,
                    "evidence": [],
                },
            ],
            "degraded": ["personal_degraded"],
            "rankings": {"dense": ["per-1", "per-2"]},
        }


def test_selected_scopes_are_fused_by_rank_and_keep_separate_projections(
    monkeypatch,
) -> None:
    captured = {}

    def public_retrieve(**arguments):
        captured.update(arguments)
        return _public_result()

    monkeypatch.setattr(
        unified_retrieval.agent_api,
        "retrieve_knowledge_result",
        public_retrieve,
    )
    personal = _PersonalService()
    result = asyncio.run(
        unified_retrieval.retrieve_selected_knowledge(
            query="question",
            top_k=3,
            similarity_threshold=0.4,
            knowledge_sources=("personal", "public"),
            user_id="trusted-user",
            knowledge_base_id="trusted-kb",
            public_service="public-service",
            personal_service=personal,
        )
    )

    assert isinstance(result, ToolExecutionResult)
    assert [item["scope"] for item in result.model_content["results"]] == [
        "personal",
        "public",
        "personal",
    ]
    assert result.model_content["execution"] == {
        "selected_sources": ["personal", "public"],
        "ranking_method": "source_rrf",
        "degraded": ["public_degraded", "personal_degraded"],
    }
    assert result.display_content["results"][0]["source"] == "Notes.txt"
    assert result.audit_metadata["public"] == {"response": "full-public"}
    assert result.audit_metadata["personal"]["rankings"]["dense"] == [
        "per-1",
        "per-2",
    ]
    assert personal.arguments == {
        "user_id": "trusted-user",
        "query": "question",
        "top_k": 3,
        "knowledge_base_id": "trusted-kb",
    }
    assert captured["service"] == "public-service"
    assert captured["similarity_threshold"] == 0.4
    serialized = json.dumps(result.model_content, ensure_ascii=False)
    assert result.model_content["budget"]["returned_token_count"] <= 2048
    assert serialized


def test_personal_only_never_calls_public_retrieval(monkeypatch) -> None:
    def unexpected_public(**_arguments):
        raise AssertionError("public retrieval must not run")

    monkeypatch.setattr(
        unified_retrieval.agent_api,
        "retrieve_knowledge_result",
        unexpected_public,
    )
    personal = _PersonalService()
    result = asyncio.run(
        unified_retrieval.retrieve_selected_knowledge(
            query="private",
            top_k=1,
            similarity_threshold=None,
            knowledge_sources=("personal",),
            user_id="trusted-user",
            knowledge_base_id="trusted-kb",
            public_service=None,
            personal_service=personal,
        )
    )

    assert result.model_content["selected_sources"] == ["personal"]
    assert result.model_content["results"][0]["scope"] == "personal"
    assert result.model_content["execution"]["ranking_method"] == "single_source_rank"
