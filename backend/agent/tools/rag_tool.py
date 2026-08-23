# backend/agent/tools/rag_tool.py

"""
这个文件干什么：把正式 RAG 检索接口注册为 ESA Agent 可调用的工具。

直白点说就是：把"查知识库"和"看知识库状态"包装成 Agent 能直接调用的两个工具。
"""

from __future__ import annotations

from typing import Any

from backend.agent.rag.agent_api import (
    knowledge_base_stats,
    retrieve_knowledge_result,
)
from backend.agent.tools.tools import tr


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "retrieve_knowledge",
            "description": (
                "从知识库检索紧凑证据。返回语义明确、受最终 JSON token 预算约束的结果；"
                "完整来源和审计数据由服务端分离处理。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "需要检索的自然语言问题",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "最多返回多少条结果，默认 5",
                        "default": 5,
                    },
                    "similarity_threshold": {
                        "type": "number",
                        "description": "可选的原始 Reranker 分数阈值；未启用时不能使用",
                    },
                },
                "required": ["query"],
            },
        },
    }
)
def retrieve_knowledge(
    query: str,
    top_k: int = 5,
    similarity_threshold: float | None = None,
) -> Any:
    """Return the current model/display/audit retrieval result."""

    return retrieve_knowledge_result(query, top_k, similarity_threshold)


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "get_knowledge_base_stats",
            "description": "读取当前知识库、模型、索引后端和检索配置。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
)
def get_knowledge_base_stats() -> dict[str, Any]:
    """返回当前注入检索服务的只读状态。"""

    return knowledge_base_stats()


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "retrieve_personal_knowledge",
            "description": (
                "检索当前登录用户主动上传的个人知识库，并返回文件名和可回查证据。"
                "用户身份由服务端会话绑定，参数中不接受 user_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "需要从个人资料中检索的自然语言问题",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "最多返回多少条结果，范围 1 到 20，默认 5",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    }
)
def retrieve_personal_knowledge(query: str, top_k: int = 5) -> dict[str, Any]:
    """Contextual tools are executed only by ``BoundToolExecutor``."""

    raise RuntimeError("personal knowledge tool requires BoundToolExecutor")
