# backend/tests/test_skill_contracts.py

"""验证 `skill_contracts` 相关行为与回归场景。"""

from backend.agent.tools.bootstrap import register_builtin_tools
from backend.agent.tools.skills import (
    build_autoload_skills_context,
    load_skill,
    refresh_skill_cache,
    validate_skill_contracts,
)
from backend.agent.tools.tools import tr


def test_skill_contracts_match_registered_tools():
    """验证 `skill_contracts_match_registered_tools` 场景。"""
    register_builtin_tools()
    refresh_skill_cache()
    errors = validate_skill_contracts(set(tr.registered_tools))
    assert errors == []


def test_new_pedagogy_skills_are_loadable():
    """验证 `new_pedagogy_skills_are_loadable` 场景。"""
    body = load_skill("progressive_hint")
    assert "Level 1" in body
    assert "Level 5" in body

    body = load_skill("error_diagnosis")
    assert "conceptual" in body
    assert "prerequisite" in body

    body = load_skill("adaptive_practice")
    assert "【练习题｜知识点" in body
    assert "record_learning_evidence" in body

    body = load_skill("math_problem_solving")
    assert "calculator" in body
    assert "math_solver" in body
    assert "bitwise_calculator" in body


def test_profile_policy_is_actually_autoloaded():
    """验证 `profile_policy_is_actually_autoloaded` 场景。"""
    context = build_autoload_skills_context()
    assert "profile_personalization" in context
    assert "工程任务" in context
