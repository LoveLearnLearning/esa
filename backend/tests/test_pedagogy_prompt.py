# backend/tests/test_pedagogy_prompt.py

"""验证 `pedagogy_prompt` 相关行为与回归场景。"""

from backend.core.message.build_prompt import build_system_prompt
from backend.core.utils.models import PromptContext


def test_system_generated_pedagogy_context_is_separate_section():
    """验证 `system_generated_pedagogy_context_is_separate_section` 场景。"""
    prompt = build_system_prompt(
        user_name="alice",
        prompt_ctx=PromptContext(
            pedagogy_context="候选教学 Skill：progressive_hint。",
            autoload_skills_context="## profile_personalization\n工程任务直接给方案。",
        ),
    )

    assert "# 教学策略路由" in prompt
    assert "progressive_hint" in prompt
    assert "# 自动启用的策略 Skill" in prompt


def test_style_rendering_does_not_print_python_tuple_repr():
    """验证 `style_rendering_does_not_print_python_tuple_repr` 场景。"""
    prompt = build_system_prompt(
        user_name="alice",
        prompt_ctx=PromptContext(
            preferred_style="concise",
            preferred_tone="friendly",
        ),
    )
    assert "风格(concise):" in prompt
    assert "('concise',)" not in prompt


def test_core_memory_is_not_eagerly_injected_into_system_prompt():
    """验证 `core_memory_is_not_eagerly_injected_into_system_prompt` 场景。"""
    prompt = build_system_prompt(
        user_name="alice",
        skills_context="- grounded_explanation [pedagogy] test",
        prompt_ctx=PromptContext(),
    )

    assert "# 核心记忆" not in prompt
    assert "暂无核心记忆" not in prompt
    assert "search_core_memories" in prompt


def test_system_prompt_defines_when_tools_must_be_used():
    """工具不能只被暴露；Prompt 必须给出可执行的调用判据。"""
    prompt = build_system_prompt(prompt_ctx=PromptContext())

    assert "# Tool 使用规则" in prompt
    assert "不要凭模型记忆猜测" in prompt
    assert "retrieve_knowledge" in prompt


def test_build_prompt_has_no_duplicate_prompt_or_style_rule_tables():
    """验证 `build_prompt_has_no_duplicate_prompt_or_style_rule_tables` 场景。"""
    import backend.core.message.build_prompt as build_prompt_module

    assert not hasattr(build_prompt_module, "SYSTEM_PROMPT")
    assert not hasattr(build_prompt_module, "_STYLE_RULES")
    assert not hasattr(build_prompt_module, "_TONE_RULES")


def test_build_prompt_reads_split_prompt_modules_at_runtime(monkeypatch):
    """验证 `build_prompt_reads_split_prompt_modules_at_runtime` 场景。"""
    import backend.core.message.system as system_message
    import backend.core.message.style_tone as style_tone

    monkeypatch.setattr(system_message, "SYSTEM_PROMPT", "SYSTEM_SOURCE_SENTINEL")
    monkeypatch.setitem(style_tone.STYLE_RULES, "concise", "STYLE_SOURCE_SENTINEL")

    prompt = build_system_prompt(
        user_name="alice",
        prompt_ctx=PromptContext(preferred_style="concise"),
    )

    assert "SYSTEM_SOURCE_SENTINEL" in prompt
    assert "STYLE_SOURCE_SENTINEL" in prompt


def test_math_workflow_is_not_eagerly_injected():
    """验证 `math_workflow_is_not_eagerly_injected` 场景。"""
    prompt = build_system_prompt(
        user_name="alice",
        skills_context=(
            "- `math_problem_solving`：数值计算、符号运算或位运算时使用"
        ),
        prompt_ctx=PromptContext(),
    )

    assert "math_problem_solving" in prompt
    assert "# 数学问题处理 Skill" not in prompt
    assert "## 工具路由" not in prompt
