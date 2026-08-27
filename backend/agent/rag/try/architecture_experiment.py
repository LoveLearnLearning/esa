"""Replay candidate integration topologies and compare end-to-end token proxies.

This deliberately measures *all* model input prompts in a tool loop, rather
than only the final projected observation.  It does not invoke an LLM and does
not claim latency milliseconds; generation/tool hop counts are authoritative.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
for path in (HERE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from projector import project_for_model  # noqa: E402
from router import Profile  # noqa: E402
from serializer import json_compact, token_count  # noqa: E402


PROJECT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "project_retrieval_context",
        "description": "把已缓存的检索结果投影为模型上下文。",
        "parameters": {
            "type": "object",
            "properties": {
                "retrieval_result_id": {"type": "string"},
                "profile": {
                    "type": "string",
                    "enum": ["MINIMAL", "SOURCE", "LOCATION", "FULL"],
                },
            },
            "required": ["retrieval_result_id", "profile"],
        },
    },
}


def _load() -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = json.loads((HERE / "fixtures" / "sample_result.json").read_text(encoding="utf-8"))
    schemas = json.loads((ROOT / "backend/agent/tools/tool_schemas.json").read_text(encoding="utf-8"))
    retrieve = next(item for item in schemas if item.get("function", {}).get("name") == "retrieve_knowledge")
    return fixture, retrieve


def _profile_argument_schema(retrieve: dict[str, Any]) -> dict[str, Any]:
    copied = json.loads(json.dumps(retrieve, ensure_ascii=False))
    properties = copied["function"]["parameters"]["properties"]
    properties["context_profile"] = {
        "type": "string",
        "enum": ["MINIMAL", "SOURCE", "LOCATION"],
        "description": "模型希望收到的检索上下文投影。",
    }
    return copied


def _assistant_call(name: str, arguments: dict[str, Any]) -> dict[str, str]:
    body = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False, separators=(",", ":"))
    return {"role": "assistant", "content": f"<tool_call>{body}</tool_call>"}


def _tool(name: str, content: Any) -> dict[str, str]:
    return {"role": "tool", "name": name, "content": json_compact(content)}


def _prompt_tokens(messages: list[dict[str, Any]], schemas: list[dict[str, Any]]) -> int:
    # Proxy for the variable portion of apply_chat_template. The same system
    # prompt and unrelated tools are intentionally omitted from every candidate.
    return token_count({"messages": messages, "tools": schemas})


def _measure(
    name: str,
    prompts: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]],
    assistant_calls: list[dict[str, str]],
    final_messages: list[dict[str, Any]],
    *,
    tool_calls: int,
    persisted_observations: list[Any],
    note: str,
) -> dict[str, Any]:
    per_generation = [_prompt_tokens(messages, schemas) for messages, schemas in prompts]
    return {
        "candidate": name,
        "generation_calls": len(prompts),
        "tool_calls": tool_calls,
        "input_prompt_proxy_tokens_by_generation": per_generation,
        "total_input_prompt_proxy_tokens": sum(per_generation),
        "final_prompt_proxy_tokens": per_generation[-1],
        "generated_tool_call_tokens": sum(token_count(item["content"]) for item in assistant_calls),
        "persisted_model_observation_tokens": sum(token_count(item) for item in persisted_observations),
        "final_message_count": len(final_messages),
        "note": note,
    }


def run() -> dict[str, Any]:
    fixture, retrieve_schema = _load()
    baseline = fixture["model_content"]
    projected = project_for_model(fixture, Profile.MINIMAL)["model_content"]
    user = {"role": "user", "content": "黑盒测试和白盒测试有什么区别？"}
    retrieve_call = _assistant_call("retrieve_knowledge", {"query": user["content"], "top_k": 3})
    project_call = _assistant_call(
        "project_retrieval_context",
        {"retrieval_result_id": "R1", "profile": "MINIMAL"},
    )

    # A and C differ in ownership, not in model-visible topology.
    ac_schemas = [retrieve_schema]
    ac_final = [user, retrieve_call, _tool("retrieve_knowledge", projected)]
    ac_prompts = [([user], ac_schemas), (ac_final, ac_schemas)]
    a = _measure(
        "A_integrated_retrieve",
        ac_prompts,
        [retrieve_call],
        ac_final,
        tool_calls=1,
        persisted_observations=[projected],
        note="Router/projector owned by retrieve_knowledge; one normal tool hop.",
    )
    c = _measure(
        "C_internal_middleware",
        ac_prompts,
        [retrieve_call],
        ac_final,
        tool_calls=1,
        persisted_observations=[projected],
        note="Same model topology as A; projection occurs after ToolExecutionResult and before ToolMessage serialization.",
    )

    # B1 reflects the current Agent loop exactly: earlier tool observations stay
    # in messages, so the unprojected retrieval is still in the final prompt.
    b_schemas = [retrieve_schema, PROJECT_TOOL_SCHEMA]
    b_after_retrieve = [user, retrieve_call, _tool("retrieve_knowledge", baseline)]
    b_final = [*b_after_retrieve, project_call, _tool("project_retrieval_context", projected)]
    b_prompts = [([user], b_schemas), (b_after_retrieve, b_schemas), (b_final, b_schemas)]
    b = _measure(
        "B_llm_tool_naive",
        b_prompts,
        [retrieve_call, project_call],
        b_final,
        tool_calls=2,
        persisted_observations=[baseline, projected],
        note="Adds a generation and tool call; baseline retrieval remains in final prompt/history, so projection does not remove it.",
    )

    # Best-case Tool interpretation: retrieval stores data out of band and only
    # returns a handle. This avoids the large first observation but changes the
    # retrieve contract and still requires an extra generation/tool/schema.
    handle = {"retrieval_result_id": "R1", "result_count": 3}
    bo_after_retrieve = [user, retrieve_call, _tool("retrieve_knowledge", handle)]
    bo_final = [*bo_after_retrieve, project_call, _tool("project_retrieval_context", projected)]
    bo_prompts = [([user], b_schemas), (bo_after_retrieve, b_schemas), (bo_final, b_schemas)]
    bo = _measure(
        "B_llm_tool_opaque_handle",
        bo_prompts,
        [retrieve_call, project_call],
        bo_final,
        tool_calls=2,
        persisted_observations=[handle, projected],
        note="Best-case separate Tool, but requires a server result registry and an extra model decision before evidence is visible.",
    )

    # D exposes profile in the existing tool schema and lets the main LLM select
    # it in the same call. It avoids a hop but repeats schema cost and delegates a
    # deterministic policy choice to the expensive answer model.
    d_schema = _profile_argument_schema(retrieve_schema)
    d_call = _assistant_call(
        "retrieve_knowledge",
        {"query": user["content"], "top_k": 3, "context_profile": "MINIMAL"},
    )
    d_final = [user, d_call, _tool("retrieve_knowledge", projected)]
    d_prompts = [([user], [d_schema]), (d_final, [d_schema])]
    d = _measure(
        "D_profile_in_tool_schema",
        d_prompts,
        [d_call],
        d_final,
        tool_calls=1,
        persisted_observations=[projected],
        note="One hop, but changes public schema and trusts the answer LLM to select a projection profile.",
    )

    candidates = [a, b, bo, c, d]
    reference = c["total_input_prompt_proxy_tokens"]
    for item in candidates:
        item["extra_input_tokens_vs_C"] = item["total_input_prompt_proxy_tokens"] - reference
        item["input_ratio_vs_C"] = round(item["total_input_prompt_proxy_tokens"] / reference, 3)
    return {
        "method": {
            "counter": "project estimate_tokens when importable; otherwise local approximation",
            "scope": "variable serialized messages + retrieval-related tool schemas over every model generation",
            "omitted_common_costs": ["system prompt", "unrelated tool schemas", "answer output tokens"],
            "caveat": "Proxy is not the deployed Qwen chat template; compare relative topology, not absolute billing.",
        },
        "fixture_tokens": {
            "current_model_content": token_count(baseline),
            "minimal_model_content": token_count(projected),
            "retrieve_schema": token_count(retrieve_schema),
            "project_tool_schema": token_count(PROJECT_TOOL_SCHEMA),
        },
        "candidates": candidates,
    }


def main() -> None:
    report = run()
    output = HERE / "results" / "architecture_comparison.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
