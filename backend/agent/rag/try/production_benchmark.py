"""Benchmark the production metadata-projection components after integration."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
for path in (ROOT, HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend.agent.rag.context_projection import (  # noqa: E402
    ContextSerializer,
    MODEL_CONTEXT_CONTRACT_VERSION,
    MetadataProjectionMiddleware,
    MetadataProjector,
)
from backend.agent.rag.context_routing import (  # noqa: E402
    MetadataProfile,
    RetrievalProjectionContext,
    RetrievalRouteInput,
    RouteDecision,
    RuleBasedContextRouter,
)
from backend.agent.rag.retrieval.context import estimate_tokens  # noqa: E402
from backend.agent.rag.unified_retrieval import (  # noqa: E402
    CONTRACT_VERSION as UNIFIED_CONTRACT_VERSION,
)
from backend.agent.tools.catalog import compact_tool_schema  # noqa: E402
from backend.agent.tools.rag_tool import retrieve_knowledge  # noqa: E402, F401
from backend.agent.tools.tools import tr  # noqa: E402
from backend.core.utils.models import ToolExecutionResult  # noqa: E402


def _serialized(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _tokens(value: Any) -> int:
    return estimate_tokens(value if isinstance(value, str) else _serialized(value))


def _fixture() -> ToolExecutionResult:
    raw = json.loads(
        (HERE / "fixtures" / "sample_result.json").read_text(encoding="utf-8")
    )
    return ToolExecutionResult(
        raw["model_content"],
        raw["display_content"],
        raw["audit_metadata"],
    )


def _context(profile: MetadataProfile, query: str) -> RetrievalProjectionContext:
    return RetrievalProjectionContext(
        enabled=True,
        route_input=RetrievalRouteInput(query),
        decision=RouteDecision(
            profile=profile,
            router_type="benchmark",
            router_version="production-components.v1",
            reason_code="fixed_profile",
        ),
    )


def _end_to_end_proxy(
    query: str,
    model_content: Any,
    retrieve_schema: dict[str, Any],
) -> int:
    user = {"role": "user", "content": query}
    call = {
        "role": "assistant",
        "content": (
            '<tool_call>{"name":"retrieve_knowledge","arguments":'
            f'{{"query":{json.dumps(query, ensure_ascii=False)}}}'
            "}</tool_call>"
        ),
    }
    tool = {
        "role": "tool",
        "name": "retrieve_knowledge",
        "content": _serialized(model_content),
    }
    first = {"messages": [user], "tools": [retrieve_schema]}
    second = {"messages": [user, call, tool], "tools": [retrieve_schema]}
    return _tokens(first) + _tokens(second)


def run() -> dict[str, Any]:
    result = _fixture()
    schema = compact_tool_schema(tr.registered_tools["retrieve_knowledge"][0])
    schema_serialized = json.dumps(schema, ensure_ascii=False, sort_keys=True)
    query = "黑盒测试和白盒测试有什么区别？"
    projector = MetadataProjector()
    serializer = ContextSerializer()
    middleware = MetadataProjectionMiddleware(projector, serializer)
    baseline_tokens = _tokens(result.model_content)
    baseline_e2e = _end_to_end_proxy(query, result.model_content, schema)
    cases = [
        {
            "case": "projection_off",
            "profile": "OFF",
            "model_content": result.model_content,
            "model_content_tokens": baseline_tokens,
            "end_to_end_input_estimate": baseline_e2e,
            "compact_text_tokens": None,
        }
    ]
    for profile in (
        MetadataProfile.MINIMAL,
        MetadataProfile.SOURCE,
        MetadataProfile.LOCATION,
        MetadataProfile.FULL,
    ):
        output = middleware.apply(result, _context(profile, query))
        projection = projector.project(result, profile)
        model_tokens = output.audit_metadata["metadata_projection"]["after_tokens"]
        cases.append(
            {
                "case": profile.value.lower(),
                "profile": profile.value,
                "model_content": output.model_content,
                "model_content_tokens": model_tokens,
                "end_to_end_input_estimate": _end_to_end_proxy(
                    query, output.model_content, schema
                ),
                "compact_text_tokens": _tokens(
                    serializer.serialize_compact_text(projection)
                ),
            }
        )
    for case in cases:
        case["saved_model_tokens"] = baseline_tokens - case["model_content_tokens"]
        case["model_saving_ratio"] = round(
            case["saved_model_tokens"] / baseline_tokens,
            6,
        )
        case["saved_end_to_end_input"] = (
            baseline_e2e - case["end_to_end_input_estimate"]
        )
        case["end_to_end_saving_ratio"] = round(
            case["saved_end_to_end_input"] / baseline_e2e,
            6,
        )
    by_profile = {case["profile"]: case["model_content"] for case in cases}
    quality_checks = [
        {
            "case": "minimal_answer_sufficiency",
            "passed": (
                [item["content"] for item in by_profile["MINIMAL"]["results"]]
                == [item["content"] for item in result.model_content["results"]]
                and all(
                    "citation_mode" in item
                    for item in by_profile["MINIMAL"]["results"]
                )
            ),
            "finding": "all ranked evidence text and citation safety modes remain",
        },
        {
            "case": "source_correctness",
            "passed": all(
                item.get("source") == "软件测试基础.pdf"
                for item in by_profile["SOURCE"]["results"]
            ),
            "finding": "source view contains document names and omits page/location",
        },
        {
            "case": "location_correctness",
            "passed": [
                item.get("page") for item in by_profile["LOCATION"]["results"]
            ]
            == [12, 13, 14],
            "finding": "location view keeps source/section/page; bbox remains server-side",
        },
        {
            "case": "full_debug_visibility",
            "passed": (
                by_profile["FULL"]["results"][0]["metadata"].get(
                    "retrieval_score"
                )
                == 0.873
            ),
            "finding": "FULL exposes bounded model/display debug metadata",
        },
    ]

    router = RuleBasedContextRouter()
    route_cases = (
        ("解释黑盒测试和白盒测试的区别", MetadataProfile.MINIMAL, "normal"),
        ("这个结论来自哪本书？", MetadataProfile.SOURCE, "source"),
        ("这段内容在第几页？", MetadataProfile.LOCATION, "location"),
        ("不用给我出处，直接解释", MetadataProfile.MINIMAL, "negation"),
        ("给出 chunk_id 和 retrieval_score", MetadataProfile.FULL, "debug"),
        # Deliberately retained as a routing boundary for future training data.
        ("这个观点最早出现在哪里？", MetadataProfile.LOCATION, "ambiguous_location"),
    )
    routing = []
    bad_cases = []
    for route_query, expected, category in route_cases:
        predicted = router.route(RetrievalRouteInput(route_query)).profile
        row = {
            "query": route_query,
            "category": category,
            "predicted_profile": predicted.value,
            "expected_profile": expected.value,
            "correct": predicted is expected,
        }
        routing.append(row)
        if not row["correct"]:
            bad_cases.append(row)

    return {
        "method": {
            "model_contract_version": MODEL_CONTEXT_CONTRACT_VERSION,
            "source_contract_version": UNIFIED_CONTRACT_VERSION,
            "tokenizer": "backend.agent.rag.retrieval.context.estimate_tokens",
            "actual_agent_tokenizer_available": False,
            "reason": "the workspace has no deployed Agent model tokenizer files",
            "end_to_end_scope": "two model input prompts; common system/history/unrelated tools omitted",
            "serializer_selected": "compact_json.v1",
            "serializer_reason": "preserves structured citation/location semantics without changing Agent serialization",
        },
        "tool_schema": {
            "name": schema["function"]["name"],
            "parameters": schema["function"]["parameters"],
            "sha256": hashlib.sha256(schema_serialized.encode()).hexdigest(),
        },
        "cases": cases,
        "routing_quality": routing,
        "bad_cases": bad_cases,
        "quality_checks": quality_checks,
    }


def main() -> None:
    report = run()
    output = HERE / "results" / "production_integration_benchmark.json"
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
