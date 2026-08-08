# backend/agent/tools/skills.py

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from backend.agent.tools.tools import tr

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
_SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class SkillValidationError(RuntimeError):
    """Skill frontmatter 或依赖契约不合法。"""


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    """一个已经解析并校验过基础字段的 Skill。"""

    name: str
    description: str
    body: str
    path: Path
    version: int = 1
    category: str = "general"
    priority: int = 50
    triggers: tuple[str, ...] = ()
    requires_tools: tuple[str, ...] = ()
    related_skills: tuple[str, ...] = ()
    autoload: bool = False


def _as_str_tuple(meta: dict[str, Any], key: str) -> tuple[str, ...]:
    value = meta.get(key, [])
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SkillValidationError(f"{key} 必须是字符串列表")
    return tuple(item.strip() for item in value if item.strip())


def _parse_skill(path: Path) -> SkillDefinition:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise SkillValidationError(
            f"{path.name} 缺少 frontmatter（文件必须以 --- 开头）"
        )

    try:
        frontmatter, body = text[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise SkillValidationError(f"{path.name} frontmatter 未闭合") from exc

    try:
        meta = yaml.safe_load(frontmatter) or {}
    except yaml.YAMLError as exc:
        raise SkillValidationError(f"{path.name} frontmatter YAML 解析失败: {exc}") from exc

    if not isinstance(meta, dict):
        raise SkillValidationError(f"{path.name} frontmatter 必须是 YAML object")

    name = str(meta.get("name", "")).strip()
    description = str(meta.get("description", "")).strip()
    body = body.strip()

    if not name:
        raise SkillValidationError(f"{path.name} 缺少 name")
    if not _SKILL_NAME_RE.fullmatch(name):
        raise SkillValidationError(
            f"{path.name} 的 name={name!r} 不合法；仅允许小写字母、数字、下划线"
        )
    if not description:
        raise SkillValidationError(f"{path.name} 缺少 description")
    if not body:
        raise SkillValidationError(f"{path.name} 正文为空")

    try:
        version = int(meta.get("version", 1))
        priority = int(meta.get("priority", 50))
    except (TypeError, ValueError) as exc:
        raise SkillValidationError(
            f"{path.name} 的 version/priority 必须是整数"
        ) from exc

    if version < 1:
        raise SkillValidationError(f"{path.name} 的 version 必须 >= 1")
    if not 0 <= priority <= 100:
        raise SkillValidationError(f"{path.name} 的 priority 必须在 0-100")

    category = str(meta.get("category", "general")).strip() or "general"
    autoload = meta.get("autoload", False)
    if not isinstance(autoload, bool):
        raise SkillValidationError(f"{path.name} 的 autoload 必须是 boolean")

    return SkillDefinition(
        name=name,
        description=description,
        body=body,
        path=path,
        version=version,
        category=category,
        priority=priority,
        triggers=_as_str_tuple(meta, "triggers"),
        requires_tools=_as_str_tuple(meta, "requires_tools"),
        related_skills=_as_str_tuple(meta, "related_skills"),
        autoload=autoload,
    )


def list_skills() -> list[Path]:
    """列举 skills 目录中的实际 Skill 文件。"""
    return sorted(
        path
        for path in SKILLS_DIR.glob("*.md")
        if path.name != "SKILLS.md"
    )


@lru_cache(maxsize=1)
def list_skill_definitions() -> tuple[SkillDefinition, ...]:
    """
    解析全部 Skill。

    生产环境按进程缓存；开发期修改 Skill 后可调用 refresh_skill_cache()。
    """
    return tuple(_parse_skill(path) for path in list_skills())


def refresh_skill_cache() -> None:
    """清除 Skill 解析/契约缓存，供热更新或测试使用。"""
    list_skill_definitions.cache_clear()
    _validated_definitions.cache_clear()


def list_skills_detail() -> list[tuple[str, str]]:
    """返回现有 Skill 的 name 和 description。"""
    return [(skill.name, skill.description) for skill in list_skill_definitions()]


def validate_skill_contracts(
    tool_names: set[str] | None = None,
) -> list[str]:
    """
    校验 Skill 之间以及 Skill -> Tool 的依赖契约。

    返回错误列表而不是直接抛异常，方便测试和启动诊断。
    """
    definitions = list_skill_definitions()
    errors: list[str] = []

    names: dict[str, Path] = {}
    for skill in definitions:
        previous = names.get(skill.name)
        if previous is not None:
            errors.append(
                f"Skill name 重复: {skill.name!r} ({previous.name}, {skill.path.name})"
            )
        else:
            names[skill.name] = skill.path

    available_skills = set(names)
    available_tools = (
        set(tr.registered_tools)
        if tool_names is None
        else set(tool_names)
    )

    for skill in definitions:
        for tool_name in skill.requires_tools:
            if tool_name not in available_tools:
                errors.append(
                    f"{skill.path.name}: requires_tools 引用了未注册工具 {tool_name!r}"
                )

        for related_name in skill.related_skills:
            if related_name not in available_skills:
                errors.append(
                    f"{skill.path.name}: related_skills 引用了不存在 Skill {related_name!r}"
                )

    return errors


@lru_cache(maxsize=1)
def _validated_definitions() -> tuple[SkillDefinition, ...]:
    errors = validate_skill_contracts()
    if errors:
        formatted = "\n".join(f"- {error}" for error in errors)
        raise SkillValidationError(f"Skill contract 校验失败:\n{formatted}")
    return list_skill_definitions()


def build_skills_context() -> str:
    """
    构建给 Agent 的 Skill 索引。

    这里只注入 name/category/description，完整正文按需通过 load_skill 加载，
    避免把所有 Skill 正文永久塞进 system prompt。
    """
    skills = sorted(
        _validated_definitions(),
        key=lambda skill: (-skill.priority, skill.name),
    )
    if not skills:
        return "暂无可用 skill"

    return "\n".join(
        f"- {skill.name} [{skill.category}] {skill.description}"
        for skill in skills
    )


def build_autoload_skills_context() -> str:
    """
    构建少量必须常驻的 policy Skill 正文。

    autoload 应只用于短、全局稳定的策略；普通教学流程仍按需 load_skill。
    """
    skills = [
        skill
        for skill in _validated_definitions()
        if skill.autoload
    ]
    if not skills:
        return ""

    skills.sort(key=lambda skill: (-skill.priority, skill.name))
    return "\n\n".join(
        f"## {skill.name}\n{skill.body}"
        for skill in skills
    )


def load_skill(name: str) -> str:
    """按 name 加载 Skill 正文。"""
    normalized = name.strip()
    for skill in _validated_definitions():
        if skill.name == normalized:
            return skill.body
    return f"{normalized} skill not found!"


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "加载某个 Skill 的详细操作说明；只有任务匹配时才调用",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Skill 名称",
                    },
                },
                "required": ["name"],
            },
        },
    }
)
def load_skill_tool(name: str) -> str:
    return load_skill(name)
