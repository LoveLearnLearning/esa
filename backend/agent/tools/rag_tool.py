# backend/agent/tools/rag_tool.py

"""
这个文件干什么：把正式 RAG 检索接口注册为 ESA Agent 可调用的工具。

直白点说就是：把"查知识库"和"看知识库状态"包装成 Agent 能直接调用的两个工具。
"""

from __future__ import annotations

from typing import Any

from backend.agent.rag.agent_api import (
    knowledge_base_stats,
    retrieve_knowledge_payload,
)
from backend.agent.tools.tools import tr


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "retrieve_knowledge",
            "description": (
                "从已配置的知识库检索证据、上下文和可回查来源。"
                "该工具只读，不会隐式建立或修改索引。"
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
                        "description": (
                            "可选的 Reranker 概率阈值；未启用 Reranker 时不能使用"
                        ),
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
) -> dict[str, Any]:
    """通过正式 RetrievalService 返回 Agent 可消费的检索结果。"""

    return retrieve_knowledge_payload(query, top_k, similarity_threshold)


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
