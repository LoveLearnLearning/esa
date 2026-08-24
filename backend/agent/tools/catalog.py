# backend/agent/tools/catalog.py

"""Single source of truth for tool scope and schema/executor visibility."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from backend.agent.tools.tool_register import ToolRegistry
from backend.core.utils.tool_arguments import normalize_tool_arguments

TOOL_CATALOG_VERSION = 2

MEMORY_READ_TOOLS = frozenset({"search_core_memories", "get_core_memories"})
MEMORY_WRITE_TOOLS = frozenset(
    {"save_core_memory", "propose_core_memory", "delete_core_memory"}
)

LEARNING_TOOLS = frozenset(
    {
        "recommend_practice", "get_mastery_report", "get_mastery_level",
        "get_weak_prerequisites", "get_review_timing",
        "record_learning_evidence", "get_learning_evidence_summary",
    }
)

COMMON_TOOLS = frozenset(
    {
        "get_weather", "get_time", "web_search", "arxiv_search", "calculator",
        "math_solver", "bitwise_calculator", "load_skill",
        "run_in_sandbox",
        "parse_pdf_attachment", "parse_word_attachment",
        "parse_presentation_attachment", "parse_spreadsheet_attachment",
        "parse_image_attachment", "retrieve_personal_knowledge",
        "retrieve_knowledge", "get_knowledge_base_stats",
    }
) | MEMORY_READ_TOOLS | MEMORY_WRITE_TOOLS

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


# The JSON schema already carries types, defaults and enums.  Keep only the
# decision-relevant sentence in the model-visible description so runtime and
# dataset prompts share one compact contract.
COMPACT_TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_weather": "查询指定城市天气。",
    "get_time": "查询当前时间。",
    "web_search": "搜索需要实时或公开网络信息的内容。",
    "arxiv_search": "搜索 arXiv 论文并返回结构化结果。",
    "calculator": "计算确定的数值表达式。",
    "math_solver": "执行符号求导、积分、求解或化简。",
    "bitwise_calculator": "执行整数位运算。",
    "run_in_sandbox": "在隔离沙箱运行受控代码或命令。",
    "load_skill": "加载一个尚未注入的候选 Skill 正文。",
    "retrieve_knowledge": "检索公共课程知识库以取得回答证据。",
    "retrieve_personal_knowledge": "检索当前用户获授权的个人知识库。",
    "get_knowledge_base_stats": "读取当前可见知识库的统计信息。",
    "save_core_memory": "按用户明确要求写入正式长期记忆。",
    "propose_core_memory": "提交推断出的长期信息供用户确认，不直接写入。",
    "search_core_memories": "按当前任务检索少量相关长期记忆。",
    "get_core_memories": "按用户明确要求列出长期记忆。",
    "delete_core_memory": "按用户明确要求删除指定长期记忆。",
    "recommend_practice": "根据课程、掌握度和考试进度推荐练习。",
    "get_mastery_report": "读取当前用户的掌握度概览。",
    "get_mastery_level": "读取当前用户指定知识点的掌握状态。",
    "get_weak_prerequisites": "读取指定知识点的薄弱前置依赖。",
    "get_review_timing": "计算指定知识点的建议复习时间。",
    "record_learning_evidence": "在真实且可评价的学习表现后写入一次学习证据。",
    "get_learning_evidence_summary": "读取当前用户近期学习证据摘要。",
    "parse_pdf_attachment": "解析当前获授权的 PDF 附件。",
    "parse_word_attachment": "解析当前获授权的 Word 附件。",
    "parse_presentation_attachment": "解析当前获授权的演示文稿附件。",
    "parse_spreadsheet_attachment": "解析当前获授权的表格附件。",
    "parse_image_attachment": "解析当前获授权的图片附件。",
    "get_teaching_context": "读取当前获授权的班级与作业上下文。",
    "start_frontier_tracking": "创建需审批的科研前沿跟踪动作。",
    "start_research_writing": "创建需审批的科研写作动作。",
    "start_dataset_analysis": "创建需审批的数据集分析动作。",
}


def compact_tool_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Project a schema without changing its executable parameter contract."""

    projected = copy.deepcopy(dict(schema))
    function = projected.get("function")
    if not isinstance(function, dict):
        return projected
    name = str(function.get("name", ""))
    if name in COMPACT_TOOL_DESCRIPTIONS:
        function["description"] = COMPACT_TOOL_DESCRIPTIONS[name]

    parameters = function.get("parameters")
    if not isinstance(parameters, dict):
        return projected
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        return projected
    for value in properties.values():
        if isinstance(value, dict):
            value.pop("description", None)

    # These distinctions are not fully represented by type/enum information.
    special = {
        ("record_learning_evidence", "self_confidence"): "学生主观自信 0-1。",
        ("record_learning_evidence", "evidence_reliability"): "本次证据可靠性 0-1。",
        ("record_learning_evidence", "correct"): "仅在可判定正误时填写。",
        ("retrieve_knowledge", "similarity_threshold"): "最低相似度阈值。",
    }
    for (tool_name, field), description in special.items():
        if name == tool_name and isinstance(properties.get(field), dict):
            properties[field]["description"] = description
    return projected


@dataclass(frozen=True, slots=True)
class CapabilityDeclaration:
    """描述单个工具或动作的版本、范围与授权要求。"""
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
            required_resource_capabilities=TOOL_RESOURCE_REQUIREMENTS.get(
                name, frozenset()
            ),
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
    """处理 `tool_scope` 相关逻辑。"""
    declaration = CAPABILITY_DECLARATIONS.get(name)
    if declaration is None:
        raise ValueError(f"tool {name!r} has no declared scope")
    return declaration.scope


def capability_declaration(name: str) -> CapabilityDeclaration:
    """返回工具或动作的规范化能力声明。"""
    try:
        return CAPABILITY_DECLARATIONS[name]
    except KeyError as error:
        raise ValueError(f"tool {name!r} has no declared capability") from error


@dataclass(frozen=True, slots=True)
class ScopedToolView:
    """封装 `ScopedToolView` 的状态与行为。"""
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
        """编译 `compile` 相关数据。

        Args:
            registry: ToolRegistry => `registry` 参数。
            scopes: frozenset[str] => `scopes` 参数。
            excluded_names: 因会话策略而禁止暴露的工具名称。
            resource_capabilities: 当前已授权资源能力。

        Returns:
            'ScopedToolView' => 处理结果。
        """
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
                entries.append((name, compact_tool_schema(schema)))
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
