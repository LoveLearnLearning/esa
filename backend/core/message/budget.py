"""Central prompt-budget policy shared by composition and model preflight."""

from __future__ import annotations

from dataclasses import dataclass
import json
from collections.abc import Callable, Sequence
from typing import Any, Mapping

from backend.core.utils.config import (
    PROMPT_AUTO_SKILL_MAX_TOKENS,
    PROMPT_BASE_TARGET_TOKENS,
    PROMPT_LAZY_SKILL_MAX_TOKENS,
    PROMPT_LEARNING_POLICY_MAX_TOKENS,
    PROMPT_LEARNING_POLICY_TARGET_TOKENS,
    PROMPT_PROFILE_MAX_TOKENS,
    PROMPT_PROFILE_TARGET_TOKENS,
    PROMPT_SAFETY_MARGIN_TOKENS,
    PROMPT_SKILL_INDEX_MAX_TOKENS,
    PROMPT_TARGET_INPUT_TOKENS,
    PROMPT_TOOL_SCHEMA_MAX_TOKENS,
    PROMPT_TOOL_SCHEMA_TARGET_TOKENS,
)
from backend.core.utils.token_estimation import estimate_tokens


@dataclass(frozen=True, slots=True)
class PromptBudgetPolicy:
    """Quality targets plus the reserve used for the physical context limit."""

    target_input_tokens: int = PROMPT_TARGET_INPUT_TOKENS
    tool_schema_target_tokens: int = PROMPT_TOOL_SCHEMA_TARGET_TOKENS
    tool_schema_max_tokens: int = PROMPT_TOOL_SCHEMA_MAX_TOKENS
    base_target_tokens: int = PROMPT_BASE_TARGET_TOKENS
    learning_policy_target_tokens: int = PROMPT_LEARNING_POLICY_TARGET_TOKENS
    learning_policy_max_tokens: int = PROMPT_LEARNING_POLICY_MAX_TOKENS
    skill_index_max_tokens: int = PROMPT_SKILL_INDEX_MAX_TOKENS
    profile_target_tokens: int = PROMPT_PROFILE_TARGET_TOKENS
    profile_max_tokens: int = PROMPT_PROFILE_MAX_TOKENS
    auto_skill_max_tokens: int = PROMPT_AUTO_SKILL_MAX_TOKENS
    lazy_skill_max_tokens: int = PROMPT_LAZY_SKILL_MAX_TOKENS
    safety_margin_tokens: int = PROMPT_SAFETY_MARGIN_TOKENS

    def hard_input_limit(self, *, max_model_len: int, max_output_tokens: int) -> int:
        """Return the maximum safe input size for one generation."""
        return max(0, max_model_len - max_output_tokens - self.safety_margin_tokens)


DEFAULT_PROMPT_BUDGET = PromptBudgetPolicy()


@dataclass(frozen=True, slots=True)
class PromptMeasurement:
    """Token accounting for the exact rendered model input."""

    input_tokens: int
    target_tokens: int
    hard_input_limit: int
    target_exceeded: bool
    hard_exceeded: bool
    estimated_sections: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class PromptArtifact:
    """A rendered prompt coupled to the measurement used to authorize it."""

    prompt: str
    measurement: PromptMeasurement


class PromptBudgetExceeded(RuntimeError):
    """Raised before generation when the physical model context cannot fit."""

    def __init__(self, measurement: PromptMeasurement) -> None:
        self.measurement = measurement
        super().__init__(
            "prompt input exceeds physical limit: "
            f"{measurement.input_tokens}>{measurement.hard_input_limit}"
        )


def measure_prompt_artifact(
    *,
    prompt: str,
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]],
    count_tokens: Callable[[str], int],
    max_model_len: int,
    max_output_tokens: int,
    policy: PromptBudgetPolicy = DEFAULT_PROMPT_BUDGET,
) -> PromptArtifact:
    """Measure an already-rendered template with a real or fake tokenizer."""

    input_tokens = count_tokens(prompt)
    hard_limit = policy.hard_input_limit(
        max_model_len=max_model_len,
        max_output_tokens=max_output_tokens,
    )
    system_text = "\n".join(
        str(message.get("content", ""))
        for message in messages
        if message.get("role") == "system"
    )
    message_text = "\n".join(
        str(message.get("content", ""))
        for message in messages
        if message.get("role") != "system"
    )
    tool_text = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
    estimates = {
        "system": estimate_tokens(system_text),
        "messages": estimate_tokens(message_text),
        "tools": estimate_tokens(tool_text),
    }
    estimates["template_overhead"] = max(
        0,
        input_tokens - sum(estimates.values()),
    )
    measurement = PromptMeasurement(
        input_tokens=input_tokens,
        target_tokens=policy.target_input_tokens,
        hard_input_limit=hard_limit,
        target_exceeded=input_tokens > policy.target_input_tokens,
        hard_exceeded=input_tokens > hard_limit,
        estimated_sections=estimates,
    )
    return PromptArtifact(prompt=prompt, measurement=measurement)
