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
    scope = skill.path.parent.name
    if scope not in {"common", "learning", "teaching", "research"}:
        raise ValueError(f"skill {skill.name!r} is outside a scoped directory")
    return scope


@dataclass(frozen=True, slots=True)
class SkillCapabilityDeclaration:
    name: str
    scope: str
    version: int
    required_resource_capabilities: frozenset[str]
    required_tools: tuple[str, ...]


def skill_declaration(skill: SkillDefinition) -> SkillCapabilityDeclaration:
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
        payload = [
            (
                skill_declaration(skill).name,
                skill_declaration(skill).version,
                skill_declaration(skill).scope,
                skill.autoload,
                skill_declaration(skill).required_tools,
                tuple(sorted(skill_declaration(skill).required_resource_capabilities)),
            )
            for skill in selected
        ]
        canonical = json.dumps(payload, separators=(",", ":"))
        fingerprint = hashlib.sha256(
            f"skills.v{SKILL_CATALOG_VERSION}:{canonical}".encode("utf-8")
        ).hexdigest()
        return cls(frozenset(scopes), selected, fingerprint)

    @property
    def names(self) -> frozenset[str]:
        return frozenset(skill.name for skill in self.definitions)

    def build_index(self) -> str:
        if not self.definitions:
            return "暂无可用 skill"
        return "\n".join(
            f"- {item.name} [{item.category}] {item.description}"
            for item in self.definitions
        )

    def build_autoload(self) -> str:
        return "\n\n".join(
            f"## {item.name}\n{item.body}"
            for item in self.definitions
            if item.autoload
        )

    def load(self, name: str) -> str:
        normalized = name.strip()
        for item in self.definitions:
            if item.name == normalized:
                return item.body
        return f"{normalized} skill not found!"
