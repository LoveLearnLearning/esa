# backend/tests/test_skill_contracts.py

"""验证 `skill_contracts` 相关行为与回归场景。"""

import json
from dataclasses import replace
from pathlib import Path

import backend.agent.skills.catalog as skill_catalog
from backend.agent.skills.catalog import ScopedSkillView
from backend.agent.tools.bootstrap import register_builtin_tools
from backend.agent.tools.skills import (
    SkillDefinition,
    build_autoload_skills_context,
    load_skill,
    refresh_skill_cache,
    skill_name_for_trigger,
    validate_skill_contracts,
)
from backend.agent.tools.tools import tr


def test_skill_contracts_match_registered_tools():
    """验证 `skill_contracts_match_registered_tools` 场景。"""
    register_builtin_tools()
    refresh_skill_cache()
    errors = validate_skill_contracts(set(tr.registered_tools))
    assert errors == []


def test_required_tools_have_actionable_skill_instructions():
    """声明依赖的 Tool 必须出现在正文中，不能只影响能力过滤。"""
    missing = {
        skill.name: [
            tool_name
            for tool_name in skill.requires_tools
            if tool_name not in skill.body
        ]
        for skill in skill_catalog.list_skill_definitions()
    }

    assert {name: tools for name, tools in missing.items() if tools} == {}


def test_tool_schema_snapshots_match_the_registered_runtime():
    """验证运行时工具 Schema 与两个版本化快照一致。"""
    register_builtin_tools()
    repository_root = Path(__file__).resolve().parents[2]
    backend_snapshot = repository_root / "backend/agent/tools/tool_schemas.json"
    dataset_snapshot = (
        repository_root / "backend/scripts/dataset/schemas/tool_schemas.json"
    )

    assert backend_snapshot.read_bytes() == dataset_snapshot.read_bytes()
    assert json.loads(backend_snapshot.read_text(encoding="utf-8")) == tr.schemas

    record_answer = next(
        schema
        for schema in tr.schemas
        if schema["function"]["name"] == "record_answer"
    )
    assert "已弃用" in record_answer["function"]["description"]


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


def test_concept_explanation_skill_answers_now_and_uses_rag():
    """概念提问应直接得到有依据的讲解，而不是先被反问。"""
    definition = next(
        skill
        for skill in skill_catalog.list_skill_definitions()
        if skill.name == "grounded_explanation"
    )

    assert "retrieve_knowledge" in definition.requires_tools
    assert "先调用 `retrieve_knowledge`" in definition.body
    assert "本轮直接回答" in definition.body
    assert "正式讲解前，先问" not in definition.body


def test_profile_policy_is_actually_autoloaded():
    """全局学习边界常驻，个性化策略按需加载。"""
    context = build_autoload_skills_context()
    assert "learning_policy" in context
    assert "profile_personalization" not in context
    assert "工程任务" in context


def test_global_learning_policy_has_no_tool_dependency():
    """学习状态服务缺失时，全局学习边界不能随个性化 Skill 一起消失。"""
    policy = next(
        skill
        for skill in skill_catalog.list_skill_definitions()
        if skill.name == "learning_policy"
    )

    assert policy.autoload is True
    assert policy.requires_tools == ()


def test_profile_personalization_is_conditional():
    """个性化 Skill 只在掌握度 Tool 可用时进入能力视图。"""
    full = ScopedSkillView.compile(
        frozenset({"learning"}),
        tool_names=frozenset({"get_mastery_level"}),
    )
    limited = ScopedSkillView.compile(
        frozenset({"learning"}),
        tool_names=frozenset(),
    )

    assert "profile_personalization" in full.names
    assert "profile_personalization" not in limited.names
    assert "learning_policy" in limited.names


def test_semantic_triggers_resolve_through_the_skill_catalog():
    assert skill_name_for_trigger("request_hint") == "progressive_hint"
    assert skill_name_for_trigger("submitted_attempt") == "homework_review"
    assert skill_name_for_trigger("explanation_request") == "grounded_explanation"


def test_skill_fingerprint_changes_when_body_changes(monkeypatch):
    """Skill behavior changes must invalidate the capability fingerprint."""
    definition = SkillDefinition(
        name="example_skill",
        description="example",
        body="first body",
        path=Path("backend/agent/skills/common/example_skill.md"),
    )
    monkeypatch.setattr(
        skill_catalog,
        "list_skill_definitions",
        lambda: (definition,),
    )
    first = ScopedSkillView.compile(frozenset({"common"})).fingerprint

    monkeypatch.setattr(
        skill_catalog,
        "list_skill_definitions",
        lambda: (replace(definition, body="second body"),),
    )
    second = ScopedSkillView.compile(frozenset({"common"})).fingerprint

    assert first != second
