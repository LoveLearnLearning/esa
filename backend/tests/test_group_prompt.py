# backend/tests/test_group_prompt.py

"""验证 `group_prompt` 相关行为与回归场景。"""

from backend.core.message.build_prompt import build_system_prompt
from backend.core.utils.models import PromptContext


def test_group_style_and_instruction_override_user_defaults() -> None:
    """验证 `group_style_and_instruction_override_user_defaults` 场景。"""
    prompt = build_system_prompt(
        user_name="tester",
        prompt_ctx=PromptContext(
            preferred_style="concise",
            preferred_tone="friendly",
            custom_instruction="默认简洁回答",
            group_style="detailed",
            group_tone="formal",
            group_custom_instruction="代码必须附带复杂度分析",
        ),
    )

    assert "风格(detailed)" in prompt
    assert "语调(formal)" in prompt
    assert "# 用户长期偏好" in prompt
    assert "# 当前分组要求" in prompt
    assert "代码必须附带复杂度分析" in prompt
    assert prompt.index("# 用户长期偏好") < prompt.index("# 当前分组要求")


def test_group_style_falls_back_to_user_style() -> None:
    """验证 `group_style_falls_back_to_user_style` 场景。"""
    prompt = build_system_prompt(
        user_name="tester",
        prompt_ctx=PromptContext(
            preferred_style="socratic",
            preferred_tone="strict",
            group_style=None,
            group_tone=None,
        ),
    )

    assert "风格(socratic)" in prompt
    assert "语调(strict)" in prompt


def test_group_style_can_override_without_custom_instruction() -> None:
    """验证 `group_style_can_override_without_custom_instruction` 场景。"""
    prompt = build_system_prompt(
        user_name="tester",
        prompt_ctx=PromptContext(
            preferred_style="concise",
            preferred_tone="friendly",
            group_style="detailed",
            group_tone="formal",
            group_custom_instruction="",
        ),
    )

    assert "风格(detailed)" in prompt
    assert "语调(formal)" in prompt
    assert "# 当前分组要求" not in prompt


def test_empty_group_context_keeps_original_behavior() -> None:
    """验证 `empty_group_context_keeps_original_behavior` 场景。"""
    prompt = build_system_prompt(
        user_name="tester",
        prompt_ctx=PromptContext(
            preferred_style="concise",
            preferred_tone="friendly",
            custom_instruction="",
            group_style=None,
            group_tone=None,
            group_custom_instruction="",
        ),
    )

    assert "风格(concise)" in prompt
    assert "语调(friendly)" in prompt
    assert "# 当前分组要求" not in prompt
