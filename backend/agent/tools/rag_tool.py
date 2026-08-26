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
                "按本轮已选择的公共/个人知识库范围检索紧凑证据。"
                "来源范围和个人身份由服务端会话绑定，不接受模型参数。"
                "返回语义明确、受最终 JSON token 预算约束的结果；"
                "完整来源和审计数据由服务端分离处理。必须遵守每条结果的 citation_mode："
                "paraphrase_only_unverified 只能转述并说明文字提取未经验证，禁止逐字引用。"
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
                            "可选的公共库原始 Reranker 分数阈值；"
                            "未启用公共库或 Reranker 时不生效"
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
