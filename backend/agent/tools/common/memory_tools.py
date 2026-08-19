# backend/agent/tools/common/memory_tools.py

"""CoreMemory V2 tool adapter using only trusted execution context."""

from __future__ import annotations

from typing import Any, Mapping

from backend.agent.tools.context import ToolExecutionContext


def _service(context: ToolExecutionContext):
    """处理 `_service` 相关逻辑。"""
    service = context.runtime_dependencies.core_memory_service
    if service is None:
        raise RuntimeError("CoreMemory service is not configured")
    return service


def execute_memory_tool(
    context: ToolExecutionContext,
    name: str,
    arguments: Mapping[str, Any],
) -> Any:
    """执行 `memory tool` 相关数据。

    Args:
        context: ToolExecutionContext => `context` 参数。
        name: str => `name` 参数。
        arguments: Mapping[str, Any] => `arguments` 参数。

    Returns:
        Any => 处理结果。
    """
    service = _service(context)
    if name == "search_core_memories":
        return service.search(
            context,
            str(arguments.get("query", "")),
            category=arguments.get("category"),
            limit=int(arguments.get("limit", 5)),
        )
    if name == "get_core_memories":
        return service.list_visible(context)
    if name == "save_core_memory":
        return service.save_explicit(
            context,
            memory_key=str(arguments.get("memory_key", "")),
            content=str(arguments.get("content", "")),
            category=str(arguments.get("category", "general")),
            scope_type=str(arguments.get("scope_type", "global")),
        )
    if name == "propose_core_memory":
        candidate = service.propose_inferred(
            context,
            memory_key=str(arguments.get("memory_key", "")),
            content=str(arguments.get("content", "")),
            category=str(arguments.get("category", "general")),
            scope_type=str(arguments.get("scope_type", "global")),
        )
        return {"status": "confirmation_required", "candidate": candidate.to_dict()}
    if name == "delete_core_memory":
        memory_id = arguments.get("memory_id")
        if not isinstance(memory_id, str):
            raise ValueError("memory_id is required")
        return {"deleted": service.forget(context, memory_id)}
    raise KeyError(name)
