"""Model-facing Tool observations stay compact and structurally valid."""

import json

from backend.agent.tool_observation import (
    compact_tool_observations,
    project_tool_result,
)
from backend.core.utils.token_estimation import estimate_tokens


def test_projection_preserves_valid_json_and_omits_oversized_scalars():
    projected = project_tool_result(
        "record_learning_evidence",
        {"saved": True, "action_id": "a1", "payload": "无标点" * 5000},
    )
    parsed = json.loads(projected)
    assert parsed["saved"] is True
    assert parsed["action_id"] == "a1"
    assert estimate_tokens(projected) <= 750
    assert "_projection" in projected


def test_cumulative_budget_compacts_oldest_receipts_and_keeps_latest():
    messages = []
    for index in range(5):
        content = project_tool_result(
            "retrieve_knowledge",
            {
                "ok": True,
                "id": f"r{index}",
                "items": [
                    {"id": f"{index}-{item}", "text": "结构化检索片段内容" * 8}
                    for item in range(500)
                ],
            },
        )
        messages.append(
            {"role": "tool", "name": "retrieve_knowledge", "content": content}
        )

    latest = messages[-1]["content"]
    assert sum(estimate_tokens(item["content"]) for item in messages) > 12_000
    compact_tool_observations(messages)

    assert sum(estimate_tokens(item["content"]) for item in messages) <= 12_000
    assert json.loads(messages[0]["content"])["_projection"]["compacted"] is True
    assert messages[-1]["content"] == latest
    assert all(isinstance(json.loads(item["content"]), dict) for item in messages)
