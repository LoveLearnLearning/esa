"""Runtime integration and isolation tests for production metadata projection."""

from __future__ import annotations

import asyncio
import json

from backend.agent.agent import Agent
from backend.agent.rag.context_projection import MODEL_CONTEXT_CONTRACT_VERSION
from backend.agent.rag.context_routing import MetadataProfile, RouteDecision
from backend.agent.rag.unified_retrieval import CONTRACT_VERSION
from backend.agent.tools.bootstrap import register_builtin_tools
from backend.agent.tools.context import AgentRuntimeDependencies
from backend.agent.tools.tools import tr
from backend.agent.workspaces.models import AgentTurnInput
from backend.agent.workspaces.runtime import WorkspaceRuntime
from backend.core.router import (
    ConversationContext,
    RoutingContext,
    TrustedIdentity,
    route_workspace,
)
from backend.core.utils.models import ParsedOutput, ToolCall, ToolExecutionResult


def _route():
    identity = TrustedIdentity("u1", "u1", "student")
    return identity, route_workspace(
        identity,
        RoutingContext(ConversationContext("c1", "u1", "learning")),
    )


def _turn(
    message: str,
    request_id: str = "r1",
    **values,
) -> AgentTurnInput:
    identity, route = _route()
    arguments = {
        "route": route,
        "identity": identity,
        "conversation_id": "c1",
        "current_message": message,
        "request_metadata": {"request_id": request_id},
    }
    arguments.update(values)
    return AgentTurnInput(
        **arguments,
    )


def _retrieval_result(query: str) -> ToolExecutionResult:
    return ToolExecutionResult(
        model_content={
            "contract_version": CONTRACT_VERSION,
            "query": query,
            "result_count": 2,
            "results": [
                {
                    "rank": 1,
                    "scope": "public",
                    "chunk_id": "a",
                    "content": "first evidence",
                    "source_ref": "ev-a",
                    "quote_eligible": False,
                    "citation_mode": "paraphrase_only_unverified",
                },
                {
                    "rank": 2,
                    "scope": "public",
                    "chunk_id": "b",
                    "content": "second evidence",
                    "source_ref": "ev-b",
                    "quote_eligible": True,
                    "citation_mode": "verbatim_allowed",
                },
            ],
            "execution": {"ranking_method": "single_source_rank"},
            "budget": {"limit": 2048},
        },
        display_content={
            "contract_version": CONTRACT_VERSION,
            "results": [
                {
                    "rank": 1,
                    "scope": "public",
                    "chunk_id": "a",
                    "source": "Testing.pdf",
                    "section": "Methods",
                    "page": 7,
                    "location": {"page": 7},
                },
                {
                    "rank": 2,
                    "scope": "public",
                    "chunk_id": "b",
                    "source": "Testing.pdf",
                    "section": "Methods",
                    "page": 8,
                    "location": {"page": 8},
                },
            ]
        },
        audit_metadata={
            "contract_version": CONTRACT_VERSION,
            "fusion": {"ranking": ["a", "b"]},
            "response": {"hits": ["full-a", "full-b"]},
        },
    )


def _dependencies(**values) -> AgentRuntimeDependencies:
    defaults = {
        "rag_service": object(),
        "metadata_projection_mode": "rule",
    }
    defaults.update(values)
    return AgentRuntimeDependencies(**defaults)


def test_runtime_routes_before_bound_retrieval_and_projects_after(monkeypatch) -> None:
    register_builtin_tools()
    original = _retrieval_result("rewritten tool query")

    async def fake_retrieve(**_arguments):
        return original

    monkeypatch.setattr(
        "backend.agent.rag.unified_retrieval.retrieve_selected_knowledge",
        fake_retrieve,
    )
    run = WorkspaceRuntime(_dependencies()).prepare(
        _turn("这段结论在第几页？")
    )
    decision = run.execution_context.retrieval_projection_context.decision
    assert decision.profile is MetadataProfile.LOCATION

    result = asyncio.run(
        run.tool_executor.execute(
            "retrieve_knowledge",
            {"query": "rewritten tool query", "top_k": 2},
        )
    )
    assert result.model_content["contract_version"] == (
        MODEL_CONTEXT_CONTRACT_VERSION
    )
    assert result.model_content["source_contract_version"] == CONTRACT_VERSION
    assert result.model_content["profile"] == "LOCATION"
    assert result.model_content["results"][0]["page"] == 7
    assert result.display_content is original.display_content
    assert result.audit_metadata["fusion"] is original.audit_metadata["fusion"]
    assert result.audit_metadata["response"] is original.audit_metadata["response"]
    assert result.audit_metadata["metadata_projection"]["query"] == "这段结论在第几页？"
    assert [
        item["chunk_id"]
        for item in result.audit_metadata["metadata_projection"]["ref_registry"].values()
    ] == ["a", "b"]


def test_feature_flag_off_returns_exact_old_three_channel_result(monkeypatch) -> None:
    register_builtin_tools()
    original = _retrieval_result("query")

    async def fake_retrieve(**_arguments):
        return original

    monkeypatch.setattr(
        "backend.agent.rag.unified_retrieval.retrieve_selected_knowledge",
        fake_retrieve,
    )
    run = WorkspaceRuntime(
        _dependencies(metadata_projection_mode="off")
    ).prepare(_turn("它来自哪本书？"))
    assert run.execution_context.retrieval_projection_context is None
    result = asyncio.run(
        run.tool_executor.execute(
            "retrieve_knowledge", {"query": "query", "top_k": 2}
        )
    )
    assert result is original


def test_runtime_dependency_default_keeps_projection_disabled() -> None:
    run = WorkspaceRuntime(AgentRuntimeDependencies(rag_service=object())).prepare(
        _turn("它来自哪本书？")
    )

    assert run.execution_context.retrieval_projection_context is None


def test_projection_exception_fails_open_without_failing_rag(monkeypatch) -> None:
    register_builtin_tools()
    original = _retrieval_result("query")

    async def fake_retrieve(**_arguments):
        return original

    def broken_apply(*_args, **_kwargs):
        raise RuntimeError("projection unavailable")

    monkeypatch.setattr(
        "backend.agent.rag.unified_retrieval.retrieve_selected_knowledge",
        fake_retrieve,
    )
    monkeypatch.setattr(
        "backend.agent.rag.context_projection.MetadataProjectionMiddleware.apply",
        broken_apply,
    )
    run = WorkspaceRuntime(_dependencies()).prepare(_turn("解释这个概念"))
    result = asyncio.run(
        run.tool_executor.execute(
            "retrieve_knowledge", {"query": "query", "top_k": 2}
        )
    )
    assert result.model_content is original.model_content
    assert result.display_content is original.display_content
    assert result.audit_metadata["metadata_projection"]["status"] == "fallback"
    assert result.audit_metadata["metadata_projection"]["fallback_reason"] == (
        "projection_error:RuntimeError"
    )


def test_router_exception_fails_open_and_is_audited(monkeypatch) -> None:
    register_builtin_tools()
    original = _retrieval_result("query")

    class BrokenRouter:
        def route(self, _route_input):
            raise RuntimeError("router unavailable")

    async def fake_retrieve(**_arguments):
        return original

    monkeypatch.setattr(
        "backend.agent.rag.unified_retrieval.retrieve_selected_knowledge",
        fake_retrieve,
    )
    run = WorkspaceRuntime(
        _dependencies(retrieval_context_router=BrokenRouter())
    ).prepare(_turn("哪一页？"))
    result = asyncio.run(
        run.tool_executor.execute(
            "retrieve_knowledge", {"query": "query", "top_k": 2}
        )
    )
    assert result.model_content is original.model_content
    assert result.audit_metadata["metadata_projection"]["fallback_reason"] == (
        "router_error:RuntimeError"
    )


def test_invalid_router_decision_fails_open_and_is_audited(monkeypatch) -> None:
    register_builtin_tools()
    original = _retrieval_result("query")

    class InvalidRouter:
        def route(self, _route_input):
            return object()

    async def fake_retrieve(**_arguments):
        return original

    monkeypatch.setattr(
        "backend.agent.rag.unified_retrieval.retrieve_selected_knowledge",
        fake_retrieve,
    )
    run = WorkspaceRuntime(
        _dependencies(retrieval_context_router=InvalidRouter())
    ).prepare(_turn("哪一页？"))
    result = asyncio.run(
        run.tool_executor.execute(
            "retrieve_knowledge", {"query": "query", "top_k": 2}
        )
    )
    assert result.model_content is original.model_content
    assert result.audit_metadata["metadata_projection"]["fallback_reason"] == (
        "router_error:TypeError"
    )


def test_custom_router_replaces_rules_without_downstream_changes(monkeypatch) -> None:
    register_builtin_tools()
    captured = {}

    class FutureFineTunedRouter:
        def route(self, route_input):
            captured["route_input"] = route_input
            return RouteDecision(
                profile=MetadataProfile.SOURCE,
                router_type="finetuned",
                router_version="model-v1",
                reason_code="predicted",
                confidence=0.93,
            )

    async def fake_retrieve(**arguments):
        return _retrieval_result(arguments["query"])

    monkeypatch.setattr(
        "backend.agent.rag.unified_retrieval.retrieve_selected_knowledge",
        fake_retrieve,
    )
    run = WorkspaceRuntime(
        _dependencies(retrieval_context_router=FutureFineTunedRouter())
    ).prepare(
        _turn(
            "普通查询",
            history=(
                {"role": "user", "content": "上一轮用户问题"},
                {"role": "assistant", "content": "上一轮回答"},
            ),
        )
    )
    result = asyncio.run(
        run.tool_executor.execute(
            "retrieve_knowledge", {"query": "query", "top_k": 2}
        )
    )
    assert result.model_content["profile"] == "SOURCE"
    assert result.model_content["contract_version"] == (
        MODEL_CONTEXT_CONTRACT_VERSION
    )
    assert result.audit_metadata["metadata_projection"]["router_type"] == "finetuned"
    assert captured["route_input"].current_user_message == "普通查询"
    assert captured["route_input"].recent_user_messages == ("上一轮用户问题",)


def test_concurrent_turns_keep_route_decisions_isolated(monkeypatch) -> None:
    register_builtin_tools()

    async def fake_retrieve(**arguments):
        await asyncio.sleep(0)
        return _retrieval_result(arguments["query"])

    monkeypatch.setattr(
        "backend.agent.rag.unified_retrieval.retrieve_selected_knowledge",
        fake_retrieve,
    )
    runtime = WorkspaceRuntime(_dependencies())
    minimal = runtime.prepare(_turn("直接解释区别", "request-a"))
    location = runtime.prepare(_turn("在哪一页？", "request-b"))
    assert (
        minimal.execution_context.retrieval_projection_context
        is not location.execution_context.retrieval_projection_context
    )

    async def execute(run, query):
        return await run.tool_executor.execute(
            "retrieve_knowledge", {"query": query, "top_k": 2}
        )

    async def collect():
        return await asyncio.gather(
            execute(minimal, "query-a"),
            execute(location, "query-b"),
        )

    first, second = asyncio.run(collect())
    assert first.model_content["profile"] == "MINIMAL"
    assert second.model_content["profile"] == "LOCATION"
    assert first.audit_metadata["metadata_projection"]["query"] == "直接解释区别"
    assert second.audit_metadata["metadata_projection"]["query"] == "在哪一页？"


def test_multiple_retrieval_calls_in_one_turn_share_only_that_turn_policy(
    monkeypatch,
) -> None:
    register_builtin_tools()

    async def fake_retrieve(**arguments):
        return _retrieval_result(arguments["query"])

    monkeypatch.setattr(
        "backend.agent.rag.unified_retrieval.retrieve_selected_knowledge",
        fake_retrieve,
    )
    run = WorkspaceRuntime(_dependencies()).prepare(
        _turn("请给出来源", "same-turn")
    )

    async def collect():
        first = await run.tool_executor.execute(
            "retrieve_knowledge", {"query": "query-one", "top_k": 2}
        )
        second = await run.tool_executor.execute(
            "retrieve_knowledge", {"query": "query-two", "top_k": 2}
        )
        return first, second

    first, second = asyncio.run(collect())
    assert first.model_content["profile"] == "SOURCE"
    assert second.model_content["profile"] == "SOURCE"
    assert first.audit_metadata["metadata_projection"]["query"] == "请给出来源"
    assert second.audit_metadata["metadata_projection"]["query"] == "请给出来源"
    assert first.audit_metadata["metadata_projection"]["ref_registry"] == (
        second.audit_metadata["metadata_projection"]["ref_registry"]
    )


def test_retrieve_tool_schema_is_unchanged() -> None:
    register_builtin_tools()
    schema = tr.registered_tools["retrieve_knowledge"][0]
    parameters = schema["function"]["parameters"]
    assert set(parameters["properties"]) == {
        "query",
        "top_k",
        "similarity_threshold",
    }
    assert parameters["required"] == ["query"]


def test_agent_tool_message_contains_projected_model_but_visible_display(monkeypatch) -> None:
    register_builtin_tools()
    original = _retrieval_result("tool query")

    async def fake_retrieve(**_arguments):
        return original

    monkeypatch.setattr(
        "backend.agent.rag.unified_retrieval.retrieve_selected_knowledge",
        fake_retrieve,
    )
    run = WorkspaceRuntime(_dependencies()).prepare(
        _turn("这个结论来自哪本书？")
    )

    class Provider:
        def __init__(self):
            self.calls = 0
            self.observed = []

        async def generate(self, messages, _schemas):
            self.observed.append([dict(item) for item in messages])
            self.calls += 1
            return "tool" if self.calls == 1 else "answer"

        def parse_output(self, response, _schemas):
            if response == "tool":
                return ParsedOutput(
                    tool_calls=[
                        ToolCall(
                            "retrieve_knowledge",
                            {"query": "tool query", "top_k": 2},
                        )
                    ]
                )
            return ParsedOutput(content="answer")

    provider = Provider()
    agent = object.__new__(Agent)
    agent.llm_provider = provider
    messages = asyncio.run(agent.run(run))

    llm_tool = provider.observed[1][-1]
    assert llm_tool["role"] == "tool"
    llm_model_content = json.loads(llm_tool["content"])
    assert llm_model_content["contract_version"] == (
        MODEL_CONTEXT_CONTRACT_VERSION
    )
    assert llm_model_content["source_contract_version"] == CONTRACT_VERSION
    assert llm_model_content["profile"] == "SOURCE"
    visible_tool = next(item for item in messages if item["role"] == "tool")
    assert json.loads(visible_tool["content"]) == original.display_content
    assert json.loads(visible_tool["model_content"])["profile"] == "SOURCE"
    assert visible_tool["audit_metadata"]["response"] == original.audit_metadata["response"]
