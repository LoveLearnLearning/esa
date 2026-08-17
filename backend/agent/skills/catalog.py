# backend/agent/skills/catalog.py

"""Scoped views over the existing validated skill catalog."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from backend.agent.tools.catalog import capability_declaration
from backend.agent.tools.skills import SkillDefinition, list_skill_definitions

SKILL_CATALOG_VERSION = 1
COMMON_CATEGORIES = frozenset({"attachment", "reasoning"})


def skill_scope(skill: SkillDefinition) -> str:
    """处理 `skill_scope` 相关逻辑。"""
    scope = skill.path.parent.name
    if scope not in {"common", "learning", "teaching", "research"}:
        raise ValueError(f"skill {skill.name!r} is outside a scoped directory")
    return scope


@dataclass(frozen=True, slots=True)
class SkillCapabilityDeclaration:
    """描述 Skill 的范围、版本、资源能力和工具依赖。"""
    name: str
    scope: str
    version: int
    required_resource_capabilities: frozenset[str]
    required_tools: tuple[str, ...]


def skill_declaration(skill: SkillDefinition) -> SkillCapabilityDeclaration:
    """从 Skill 元数据及其工具依赖派生能力声明。"""
    resources: set[str] = set()
    for tool_name in skill.requires_tools:
        resources.update(
            capability_declaration(tool_name).required_resource_capabilities
        )
    return SkillCapabilityDeclaration(
        name=skill.name,
        scope=skill_scope(skill),
        version=skill.version,
        required_resource_capabilities=frozenset(resources),
        required_tools=skill.requires_tools,
    )


@dataclass(frozen=True, slots=True)
class ScopedSkillView:
    """封装 `ScopedSkillView` 的状态与行为。"""
    scopes: frozenset[str]
    definitions: tuple[SkillDefinition, ...]
    fingerprint: str

    @classmethod
    def compile(
        cls,
        scopes: frozenset[str],
        *,
        tool_names: frozenset[str] | None = None,
    ) -> "ScopedSkillView":
        """编译 `compile` 相关数据。

        Args:
            scopes: frozenset[str] => `scopes` 参数。
            tool_names: 当前运行时实际可用的工具名称；用于过滤依赖缺失的 Skill。

        Returns:
            'ScopedSkillView' => 处理结果。
        """
        selected = tuple(
            sorted(
                (
                    skill
                    for skill in list_skill_definitions()
                    if skill_scope(skill) in scopes
                    and (
                        tool_names is None
                        or set(skill.requires_tools) <= tool_names
                    )
                ),
                key=lambda skill: (-skill.priority, skill.name),
            )
        )
        declarations = tuple(skill_declaration(skill) for skill in selected)
        payload = [
            (
                declaration.name,
                declaration.version,
                declaration.scope,
                skill.category,
                skill.description,
                skill.priority,
                skill.autoload,
                skill.triggers,
                skill.related_skills,
                declaration.required_tools,
                tuple(sorted(declaration.required_resource_capabilities)),
                hashlib.sha256(skill.body.encode("utf-8")).hexdigest(),
            )
            for skill, declaration in zip(selected, declarations)
        ]
        canonical = json.dumps(payload, separators=(",", ":"))
        fingerprint = hashlib.sha256(
            f"skills.v{SKILL_CATALOG_VERSION}:{canonical}".encode("utf-8")
        ).hexdigest()
        return cls(frozenset(scopes), selected, fingerprint)

    @property
    def names(self) -> frozenset[str]:
        """处理 `names` 相关逻辑。"""
        return frozenset(skill.name for skill in self.definitions)

    def build_index(self) -> str:
        """构建 `index` 相关数据。"""
        if not self.definitions:
            return "暂无可用 skill"
        return "\n".join(
            f"- {item.name} [{item.category}] {item.description}"
            for item in self.definitions
        )

    def build_autoload(self) -> str:
        """构建 `autoload` 相关数据。"""
        return "\n\n".join(
            f"## {item.name}\n{item.body}"
            for item in self.definitions
            if item.autoload
        )

    def load(self, name: str) -> str:
        """加载 `load` 相关数据。"""
        normalized = name.strip()
        for item in self.definitions:
            if item.name == normalized:
                return item.body
        return f"{normalized} skill not found!"
