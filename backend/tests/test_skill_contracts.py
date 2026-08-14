import json
from pathlib import Path

from backend.agent.tools.bootstrap import register_builtin_tools
from backend.agent.tools.skills import (
    build_autoload_skills_context,
    load_skill,
    refresh_skill_cache,
    validate_skill_contracts,
)
from backend.agent.tools.tools import tr


def test_skill_contracts_match_registered_tools():
    register_builtin_tools()
    refresh_skill_cache()
    errors = validate_skill_contracts(set(tr.registered_tools))
    assert errors == []


def test_tool_schema_snapshots_match_the_registered_runtime():
    register_builtin_tools()
    repository_root = Path(__file__).resolve().parents[2]
    backend_snapshot = repository_root / "backend/agent/tools/tool_schemas.json"
    dataset_snapshot = (
        repository_root / "backend/scripts/dataset/schemas/tool_schemas.json"
    )

    assert backend_snapshot.read_bytes() == dataset_snapshot.read_bytes()
    assert json.loads(backend_snapshot.read_text(encoding="utf-8")) == tr.schemas


def test_new_pedagogy_skills_are_loadable():
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
    context = build_autoload_skills_context()
    assert "profile_personalization" in context
    assert "工程任务" in context
