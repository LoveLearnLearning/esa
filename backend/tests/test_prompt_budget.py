"""Synthetic, model-free regression tests for prompt quality budgets."""

from __future__ import annotations

import json
import math
from pathlib import Path

from backend.agent.memories.memory_models import (
    ProfileField,
    ProfileOrigin,
    ProfileSnapshot,
)
from backend.agent.tools.bootstrap import register_builtin_tools
from backend.agent.tools.context import AgentRuntimeDependencies
from backend.agent.workspaces.capability_runtime import CapabilityRuntime
from backend.agent.workspaces.models import AgentTurnInput, LearningTurnContext
from backend.agent.workspaces.runtime import WorkspaceRuntime
from backend.core.message.budget import (
    PromptBudgetPolicy,
    measure_prompt_artifact,
)
from backend.core.router.basic_router import route_workspace
from backend.core.router.context import (
    AttachmentAuthorization,
    ConversationContext,
    RoutingContext,
)
from backend.core.router.models import TrustedIdentity
from backend.core.utils.token_estimation import estimate_tokens


FIXTURE = Path(__file__).with_name("fixtures") / "prompt_budget_scenarios.json"


def _route(*, attachment: bool = False):
    identity = TrustedIdentity("u1", "alice", "student")
    return identity, route_workspace(
        identity,
        RoutingContext(
            ConversationContext("c1", "u1", "learning"),
            attachments=AttachmentAuthorization(("a1",) if attachment else ()),
            resource_capabilities=(
                frozenset({"attachments"}) if attachment else frozenset()
            ),
        ),
    )


def _profile() -> ProfileSnapshot:
    return ProfileSnapshot(
        user_id="u1",
        profile_version=1,
        explicit_context=[
            ProfileField("major", "计算机", ProfileOrigin.EXPLICIT_SETTING),
            ProfileField("current_week", 12, ProfileOrigin.EXPLICIT_SETTING),
        ],
        relevant_learning_state=[
            ProfileField(
                "mastery",
                {
                    "kp_id": "动态规划",
                    "name": "动态规划",
                    "mastery": {"has_record": True, "level": 62},
                },
                ProfileOrigin.DERIVED_LEARNING_STATE,
            )
        ],
    )


def test_synthetic_first_turn_prompt_p95_meets_quality_target():
    register_builtin_tools()
    scenarios = json.loads(FIXTURE.read_text(encoding="utf-8"))
    estimates = []
    for index, scenario in enumerate(scenarios):
        identity, route = _route(attachment=bool(scenario.get("attachment")))
        history = (
            ({"role": "assistant", "content": "【练习题｜知识点：哈希表】..."},)
            if scenario.get("history_marker")
            else ()
        )
        turn = AgentTurnInput(
            route=route,
            identity=identity,
            conversation_id="c1",
            current_message=scenario["message"],
            task_mode=scenario.get("task_mode"),
            history=history,
            conversation_mode=scenario.get("conversation_mode", "normal"),
            profile_snapshot=_profile() if scenario.get("profile") else None,
            learning_context=LearningTurnContext(
                resolved_kp_ids=tuple(scenario.get("kp_ids", ())),
                pending_practice_kp_id=scenario.get("pending_kp_id"),
            ),
            authorized_attachments=(
                ({"attachment_id": "a1", "media_type": "application/pdf"},)
                if scenario.get("attachment")
                else ()
            ),
            request_metadata={"request_id": f"synthetic-{index}"},
        )
        run = WorkspaceRuntime(AgentRuntimeDependencies()).prepare(turn)
        compact_tools = json.dumps(
            run.tool_schemas,
            ensure_ascii=False,
            separators=(",", ":"),
            default=dict,
        )
        prompt_estimate = sum(
            estimate_tokens(str(message.get("content", "")))
            for message in run.messages
        ) + estimate_tokens(compact_tools) + 256
        estimates.append(prompt_estimate)
        assert estimate_tokens(compact_tools) <= 3000, scenario["name"]

    p95 = sorted(estimates)[math.ceil(len(estimates) * 0.95) - 1]
    assert p95 <= 5000, dict(zip((item["name"] for item in scenarios), estimates))


def test_fake_tokenizer_covers_soft_and_physical_budget_branches():
    policy = PromptBudgetPolicy(target_input_tokens=5000, safety_margin_tokens=512)
    target_only = measure_prompt_artifact(
        prompt="rendered",
        messages=[{"role": "system", "content": "rules"}],
        tools=[],
        count_tokens=lambda _text: 5001,
        max_model_len=10_000,
        max_output_tokens=1000,
        policy=policy,
    )
    assert target_only.measurement.target_exceeded is True
    assert target_only.measurement.hard_exceeded is False

    physical = measure_prompt_artifact(
        prompt="rendered",
        messages=[{"role": "user", "content": "question"}],
        tools=[],
        count_tokens=lambda _text: 5001,
        max_model_len=6000,
        max_output_tokens=500,
        policy=policy,
    )
    assert physical.measurement.hard_input_limit == 4988
    assert physical.measurement.hard_exceeded is True
    assert set(physical.measurement.estimated_sections) == {
        "system", "messages", "tools", "template_overhead"
    }


def test_skill_index_uses_complete_lines_within_fixed_budget():
    register_builtin_tools()
    compiled = CapabilityRuntime().compile(
        skill_scopes=frozenset({"common", "learning"}),
        tool_scopes=frozenset({"common", "learning"}),
        profile_fingerprint="learning:budget",
        policy_versions=("learning.v1",),
        resource_capabilities=frozenset({"attachments"}),
        has_attachments=True,
    )
    index = compiled.capabilities.skill_index
    assert estimate_tokens(index) <= 250
    assert all(":" in line for line in index.splitlines())
    assert "learning_policy" not in index
