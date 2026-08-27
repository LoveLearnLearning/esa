"""Production projector, serializer, observability, and fallback tests."""

import json

from backend.agent.rag.context_projection import (
    ContextSerializer,
    MetadataProjectionMiddleware,
    MetadataProjector,
)
from backend.agent.rag.context_routing import (
    MetadataProfile,
    RetrievalProjectionContext,
    RetrievalRouteInput,
    RouteDecision,
)
from backend.core.utils.models import ToolExecutionResult


def _result(*, missing: bool = False) -> ToolExecutionResult:
    model = {
        "contract_version": "retrieve_knowledge.unified.v1",
        "query": "黑盒与白盒",
        "results": [
            {
                "rank": 1,
                "scope": "public",
                "chunk_id": "chunk-a",
                "content": "黑盒关注输入/输出，特殊字符：\"引号\"与换行\n正常。",
                "source_ref": "evidence-a",
                "quote_eligible": False,
                "citation_mode": "paraphrase_only_unverified",
                "retrieval_score": 0.9,
            },
            {
                "rank": 2,
                "scope": "personal",
                "chunk_id": "chunk-b",
                "content": "白盒关注内部路径。",
                "source_ref": "evidence-b",
                "quote_eligible": True,
                "citation_mode": "verbatim_allowed",
            },
        ],
        "execution": {"ranking_method": "source_rrf"},
        "budget": {"limit": 2048},
    }
    display = {
        "contract_version": "retrieve_knowledge.unified.v1",
        "results": [
            {
                "rank": 1,
                "scope": "public",
                "chunk_id": "chunk-a",
                "source_ref": "evidence-a",
                "document_id": "doc-a",
                "source": None if missing else "软件测试基础.pdf",
                "section": None if missing else "第三章 / 测试方法",
                "page": None if missing else 12,
                "location": None if missing else {"page": 12, "bbox": [1, 2, 3, 4]},
                "preview_url": "/documents/doc-a",
            },
            {
                "rank": 2,
                "scope": "personal",
                "chunk_id": "chunk-b",
                "source_ref": "evidence-b",
                "source": "Notes.txt",
                "section": "One",
                "page": 3,
                "location": {"page": 3},
            },
        ],
    }
    return ToolExecutionResult(
        model_content=model,
        display_content=display,
        audit_metadata={"contract_version": "retrieve_knowledge.unified.v1", "trace": {"full": True}},
    )


def _context(profile: MetadataProfile) -> RetrievalProjectionContext:
    return RetrievalProjectionContext(
        enabled=True,
        route_input=RetrievalRouteInput("测试查询"),
        decision=RouteDecision(
            profile=profile,
            router_type="rule",
            router_version="v1",
            reason_code="test",
        ),
    )


def test_projector_profiles_have_exact_progressive_fields() -> None:
    projector = MetadataProjector()
    result = _result()
    minimal = projector.project(result, MetadataProfile.MINIMAL).results[0]
    source = projector.project(result, MetadataProfile.SOURCE).results[0]
    location = projector.project(result, MetadataProfile.LOCATION).results[0]
    full = projector.project(result, MetadataProfile.FULL).results[0]

    assert set(minimal) == {"ref", "content", "citation_mode"}
    assert source["source"] == "软件测试基础.pdf"
    assert "page" not in source and "location" not in source
    assert location["section"] == "第三章 / 测试方法"
    assert location["page"] == 12
    assert "location" not in location
    assert full["metadata"]["chunk_id"] == "chunk-a"
    assert full["metadata"]["retrieval_score"] == 0.9


def test_middleware_projects_only_model_content_and_preserves_provenance() -> None:
    result = _result()
    projected = MetadataProjectionMiddleware().apply(
        result,
        _context(MetadataProfile.MINIMAL),
        token_counter=lambda text: len(text.encode("utf-8")),
    )

    assert projected.model_content["profile"] == "MINIMAL"
    assert projected.display_content is result.display_content
    assert projected.audit_metadata["contract_version"] == result.audit_metadata["contract_version"]
    assert projected.audit_metadata["trace"] is result.audit_metadata["trace"]
    metrics = projected.audit_metadata["metadata_projection"]
    assert metrics["status"] == "applied"
    assert metrics["counter"] == "agent_tokenizer"
    assert metrics["before_tokens"] > metrics["after_tokens"]
    assert metrics["ref_registry"]["C1"]["source_ref"] == "evidence-a"
    assert metrics["ref_registry"]["C1"]["document_id"] == "doc-a"
    assert "before_tokens" not in json.dumps(projected.model_content)


def test_projected_content_over_budget_fails_open_and_audits_candidate() -> None:
    result = _result()
    result.model_content["budget"]["limit"] = 1

    fallback = MetadataProjectionMiddleware().apply(
        result,
        _context(MetadataProfile.MINIMAL),
        token_counter=lambda text: len(text.encode("utf-8")),
    )

    assert fallback.model_content is result.model_content
    assert fallback.display_content is result.display_content
    metadata = fallback.audit_metadata["metadata_projection"]
    assert metadata["status"] == "fallback"
    assert metadata["fallback_reason"] == "projected_model_budget_exceeded"
    assert metadata["candidate_after_tokens"] > metadata["limit"] == 1
    assert metadata["counter"] == "agent_tokenizer"
    assert metadata["serializer"] == "compact_json.v1"


def test_serializer_is_stable_unicode_safe_and_keeps_content_order() -> None:
    projection = MetadataProjector().project(_result(), MetadataProfile.MINIMAL)
    serializer = ContextSerializer()
    first = serializer.serialize(projection)
    second = serializer.serialize(projection)

    assert first == second
    assert [item["ref"] for item in first["results"]] == ["C1", "C2"]
    assert "特殊字符" in first["results"][0]["content"]
    assert "\n" in first["results"][0]["content"]
    encoded = json.dumps(first, ensure_ascii=False)
    assert "特殊字符" in encoded
    text = serializer.serialize_compact_text(projection)
    assert text.index("[C1]") < text.index("[C2]")
    assert "黑盒关注输入/输出" in text


def test_location_missing_metadata_degrades_without_fabrication() -> None:
    result = _result(missing=True)
    projected = MetadataProjectionMiddleware().apply(
        result,
        _context(MetadataProfile.LOCATION),
    )
    first = projected.model_content["results"][0]
    assert first["source"] is None
    assert first["section"] is None
    assert first["page"] is None
    assert first["location"] is None
    assert projected.audit_metadata["metadata_projection"]["missing_metadata"] == [
        "C1.source",
        "C1.section",
        "C1.page",
        "C1.location",
    ]


def test_missing_route_decision_fails_open_to_original_model_content() -> None:
    result = _result()
    context = RetrievalProjectionContext(
        enabled=True,
        route_input=RetrievalRouteInput("query"),
        fallback_reason="router_error:RuntimeError",
    )
    fallback = MetadataProjectionMiddleware().apply(result, context)
    assert fallback.model_content is result.model_content
    assert fallback.display_content is result.display_content
    assert fallback.audit_metadata["trace"] == result.audit_metadata["trace"]
    assert fallback.audit_metadata["metadata_projection"] == {
        "enabled": True,
        "status": "fallback",
        "fallback_reason": "router_error:RuntimeError",
        "query": "query",
        "recent_user_messages": [],
    }


def test_disabled_context_returns_exact_old_result_object() -> None:
    result = _result()
    disabled = RetrievalProjectionContext(
        enabled=False,
        route_input=RetrievalRouteInput("query"),
    )
    assert MetadataProjectionMiddleware().apply(result, disabled) is result
