# backend/agent/tools/catalog.py

"""Single source of truth for tool scope and schema/executor visibility."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from backend.agent.tools.tool_register import ToolRegistry
from backend.core.utils.tool_arguments import normalize_tool_arguments

TOOL_CATALOG_VERSION = 1

LEARNING_TOOLS = frozenset(
    {
        "recommend_practice", "get_mastery_report", "get_mastery_level",
        "get_weak_prerequisites", "get_review_timing", "record_answer",
        "record_learning_evidence", "get_learning_evidence_summary",
        "retrieve_knowledge", "get_knowledge_base_stats",
    }
)

COMMON_TOOLS = frozenset(
    {
        "get_weather", "get_time", "web_search", "arxiv_search", "calculator",
        "math_solver", "bitwise_calculator", "load_skill", "save_core_memory",
        "propose_core_memory", "search_core_memories", "get_core_memories",
        "delete_core_memory",
        "parse_pdf_attachment", "parse_word_attachment",
        "parse_presentation_attachment", "parse_spreadsheet_attachment",
        "parse_image_attachment",
    }
)

RESEARCH_TOOLS = frozenset(
    {
        "start_frontier_tracking",
        "start_research_writing",
        "start_dataset_analysis",
    }
)

TEACHING_TOOLS = frozenset()


def tool_scope(name: str) -> str:
    """处理 `tool_scope` 相关逻辑。"""
    if name in LEARNING_TOOLS:
        return "learning"
    if name in COMMON_TOOLS:
        return "common"
    if name in RESEARCH_TOOLS:
        return "research"
    if name in TEACHING_TOOLS:
        return "teaching"
    raise ValueError(f"tool {name!r} has no declared scope")


@dataclass(frozen=True, slots=True)
class ScopedToolView:
    """封装 `ScopedToolView` 的状态与行为。"""
    registry: ToolRegistry
    scopes: frozenset[str]
    names: frozenset[str]
    schemas: tuple[dict[str, Any], ...]
    fingerprint: str

    @classmethod
    def compile(cls, registry: ToolRegistry, scopes: frozenset[str]) -> "ScopedToolView":
        """编译 `compile` 相关数据。

        Args:
            registry: ToolRegistry => `registry` 参数。
            scopes: frozenset[str] => `scopes` 参数。

        Returns:
            'ScopedToolView' => 处理结果。
        """
        entries = []
        for name, (schema, _handler) in registry.registered_tools.items():
            if tool_scope(name) in scopes:
                entries.append((name, copy.deepcopy(schema)))
        entries.sort(key=lambda item: item[0])
        canonical = json.dumps(
            entries,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = hashlib.sha256(
            f"tools.v{TOOL_CATALOG_VERSION}:{canonical}".encode("utf-8")
        ).hexdigest()
        return cls(
            registry=registry,
            scopes=frozenset(scopes),
            names=frozenset(name for name, _ in entries),
            schemas=tuple(schema for _, schema in entries),
            fingerprint=fingerprint,
        )

    def contains(self, name: str) -> bool:
        """处理 `contains` 相关逻辑。"""
        return name in self.names

    def normalize_arguments(
        self, name: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        """规范化 `arguments` 相关数据。

        Args:
            name: str => `name` 参数。
            arguments: Mapping[str, Any] => `arguments` 参数。

        Returns:
            dict[str, Any] => 处理结果。
        """
        if name not in self.names:
            raise KeyError(name)
        schema = self.registry.registered_tools[name][0]
        parameters = schema.get("function", {}).get("parameters", {})
        properties = parameters.get("properties", {})
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            raise ValueError(
                f"undeclared arguments for {name}: {', '.join(unknown)}"
            )
        missing = sorted(set(parameters.get("required", ())) - set(arguments))
        if missing:
            raise ValueError(
                f"missing required arguments for {name}: {', '.join(missing)}"
            )
        return normalize_tool_arguments(schema, dict(arguments))

    async def execute(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """执行 `execute` 相关数据。

        Args:
            name: str => `name` 参数。
            arguments: Mapping[str, Any] => `arguments` 参数。

        Returns:
            Any => 处理结果。
        """
        if name not in self.names:
            return {
                "ok": False,
                "error": "tool_not_available",
                "tool": name,
            }
        try:
            normalized = self.normalize_arguments(name, arguments)
        except (KeyError, ValueError) as error:
            return {
                "ok": False,
                "error": "invalid_tool_arguments",
                "tool": name,
                "detail": str(error),
            }
        return await self.registry.acall(name, normalized)
