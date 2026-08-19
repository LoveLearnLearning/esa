# backend/agent/tools/web_search.py

"""Stable Agent-facing adapter for the You.com MCP search tool."""

from __future__ import annotations

from typing import Any, Mapping

from backend.agent.tools.context import ToolExecutionContext
from backend.agent.tools.tools import tr
from backend.core.log.logger import pipeline_log_context


YOU_MCP_SERVER = "you"
YOU_MCP_SEARCH_TOOL = "you-search"


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "通过互联网搜索信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索内容",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大搜索结果，默认为 5 ",
                        "default": 5,
                    },
                    "language": {
                        "type": "string",
                        "description": "搜索结果便好语言，默认为中文",
                        "default": "zh-CN",
                    },
                    "time_range": {
                        "type": "string",
                        "enum": ["day", "month", "year"],
                        "description": "搜索时间范围，可选天月年",
                    },
                },
                "required": ["query"],
            },
        },
    }
)
def web_search(
    query: str,
    max_results: int = 5,
    language: str = "zh-CN",
    time_range: str | None = None,
) -> dict[str, Any]:
    """Reject unbound calls; production execution needs the lifespan MCP client."""

    del query, max_results, language, time_range
    raise RuntimeError("web_search requires the application MCP runtime")


def _schema_properties(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    properties = schema.get("properties", {})
    return properties if isinstance(properties, Mapping) else {}


def build_you_search_arguments(
    schema: Mapping[str, Any],
    *,
    query: str,
    max_results: int = 5,
    language: str = "zh-CN",
    time_range: str | None = None,
) -> dict[str, Any]:
    """Map ESA's stable search contract onto the discovered MCP schema."""

    query = query.strip()
    if not query:
        raise ValueError("搜索关键词不能为空")
    properties = _schema_properties(schema)
    arguments: dict[str, Any] = {}

    query_key = next(
        (key for key in ("query", "q", "search_query") if key in properties),
        None,
    )
    if query_key is None:
        raise RuntimeError("You.com MCP search schema does not declare a query field")
    arguments[query_key] = query

    max_results = max(1, min(max_results, 20))
    for key in ("max_results", "count", "limit", "num_results"):
        if key in properties:
            arguments[key] = max_results
            break
    for key in ("language", "search_language", "search_lang"):
        if key in properties:
            arguments[key] = language
            break
    if time_range in {"day", "month", "year"}:
        for key in ("time_range", "freshness", "recency"):
            definition = properties.get(key)
            if not isinstance(definition, Mapping):
                continue
            allowed = definition.get("enum")
            if allowed is None or time_range in allowed:
                arguments[key] = time_range
                break
    return arguments


async def execute_web_search(
    context: ToolExecutionContext,
    *,
    query: str,
    max_results: int = 5,
    language: str = "zh-CN",
    time_range: str | None = None,
) -> dict[str, Any]:
    """Execute You.com search through the lifecycle-owned MCP child process."""

    manager = context.runtime_dependencies.mcp_client_manager
    if manager is None:
        raise RuntimeError("You.com MCP search service is not configured")
    schema = manager.tool_schema(YOU_MCP_SERVER, YOU_MCP_SEARCH_TOOL)
    arguments = build_you_search_arguments(
        schema,
        query=query,
        max_results=max_results,
        language=language,
        time_range=time_range,
    )
    with pipeline_log_context(
        user_id=context.user_id,
        conversation_id=context.conversation_id,
    ):
        result = await manager.call_tool(
            YOU_MCP_SERVER,
            YOU_MCP_SEARCH_TOOL,
            arguments,
        )
    return {
        "provider": "you.com",
        "query": query.strip(),
        **result,
    }
