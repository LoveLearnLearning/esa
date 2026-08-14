"""Single source of truth for tool scope and schema/executor visibility."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping

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
        "propose_core_memory", "search_core_memories",
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

TEACHING_TOOLS = frozenset({"get_teaching_context"})

TOOL_RESOURCE_REQUIREMENTS: dict[str, frozenset[str]] = {
    "start_frontier_tracking": frozenset({"research_project"}),
    "start_research_writing": frozenset({"research_project"}),
    "start_dataset_analysis": frozenset({"research_project"}),
    "parse_pdf_attachment": frozenset({"attachments"}),
    "parse_word_attachment": frozenset({"attachments"}),
    "parse_presentation_attachment": frozenset({"attachments"}),
    "parse_spreadsheet_attachment": frozenset({"attachments"}),
    "parse_image_attachment": frozenset({"attachments"}),
    "get_teaching_context": frozenset({"classroom"}),
}


@dataclass(frozen=True, slots=True)
class CapabilityDeclaration:
    name: str
    scope: str
    version: int = 1
    required_resource_capabilities: frozenset[str] = frozenset()
    kind: Literal["tool", "action"] = "tool"
    approval_mode: Literal[
        "automatic", "approval_required", "forbidden"
    ] | None = None
    policy_version: str = "capability.v1"


CAPABILITY_DECLARATIONS: dict[str, CapabilityDeclaration] = {
    **{
        name: CapabilityDeclaration(
            name,
            "common",
            required_resource_capabilities=TOOL_RESOURCE_REQUIREMENTS.get(
                name, frozenset()
            ),
        )
        for name in COMMON_TOOLS
    },
    **{name: CapabilityDeclaration(name, "learning") for name in LEARNING_TOOLS},
    **{
        name: CapabilityDeclaration(
            name,
            "research",
            required_resource_capabilities=TOOL_RESOURCE_REQUIREMENTS[name],
            kind="action",
            approval_mode="approval_required",
            policy_version="research.v1",
        )
        for name in RESEARCH_TOOLS
    },
    **{
        name: CapabilityDeclaration(
            name,
            "teaching",
            required_resource_capabilities=TOOL_RESOURCE_REQUIREMENTS.get(
                name, frozenset()
            ),
            policy_version="teaching.v1",
        )
        for name in TEACHING_TOOLS
    },
}


def tool_scope(name: str) -> str:
    declaration = CAPABILITY_DECLARATIONS.get(name)
    if declaration is None:
        raise ValueError(f"tool {name!r} has no declared scope")
    return declaration.scope


def capability_declaration(name: str) -> CapabilityDeclaration:
    try:
        return CAPABILITY_DECLARATIONS[name]
    except KeyError as error:
        raise ValueError(f"tool {name!r} has no declared capability") from error


@dataclass(frozen=True, slots=True)
class ScopedToolView:
    registry: ToolRegistry
    scopes: frozenset[str]
    names: frozenset[str]
    schemas: tuple[dict[str, Any], ...]
    fingerprint: str

    @classmethod
    def compile(
        cls,
        registry: ToolRegistry,
        scopes: frozenset[str],
        *,
        excluded_names: frozenset[str] = frozenset(),
        resource_capabilities: frozenset[str] | None = None,
    ) -> "ScopedToolView":
        entries = []
        for name, (schema, _handler) in registry.registered_tools.items():
            required = TOOL_RESOURCE_REQUIREMENTS.get(name, frozenset())
            resource_allowed = (
                resource_capabilities is None
                or required.issubset(resource_capabilities)
            )
            if (
                name not in excluded_names
                and tool_scope(name) in scopes
                and resource_allowed
            ):
                entries.append((name, copy.deepcopy(schema)))
        entries.sort(key=lambda item: item[0])
        canonical = json.dumps(
            [
                (name, CAPABILITY_DECLARATIONS[name].version, schema)
                for name, schema in entries
            ],
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
        return name in self.names

    def normalize_arguments(
        self, name: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
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
