"""Central prompt-budget policy shared by composition and model preflight."""

from __future__ import annotations

from dataclasses import dataclass

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
