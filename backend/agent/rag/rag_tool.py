# backend/agent/rag/rag_tool.py
"""
RAG 工具注册

将 RAG 检索功能注册为 Agent 工具，使其能够被 Agent 自动调用。
"""

from typing import Any, Optional

from backend.agent.rag.config import RAGConfig
from backend.agent.rag.retriever import get_retriever, reset_retriever
from backend.agent.tools.tools import tr


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "retrieve_knowledge",
            "description": "从知识库中检索与查询相关的文档片段。返回结果包含文档内容、来源信息和相似度得分。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "查询文本，描述需要检索的内容",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回的最大结果数量，默认为 5",
                        "default": 5,
                    },
                    "similarity_threshold": {
                        "type": "number",
                        "description": "相似度阈值（0-1），低于此值的结果将被过滤，默认为 0.5",
                        "default": 0.5,
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
    similarity_threshold: float = 0.5,
) -> dict[str, Any]:
    """从知识库检索相关文档

    Args:
        query: 查询文本
        top_k: 返回的最大结果数量
        similarity_threshold: 相似度阈值

    Returns:
        dict: 检索结果，包含查询、结果数量、文档片段和来源信息
    """
    retriever = get_retriever()

    # 检索结果
    result = retriever.retrieve_with_context(
        query=query,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
    )

    return result


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "index_knowledge_base",
            "description": "将文档目录索引到知识库中，使其可以被检索。支持 .txt 和 .md 格式的文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir_path": {
                        "type": "string",
                        "description": "文档目录路径，默认使用系统配置的路径",
                    },
                },
                "required": [],
            },
        },
    }
)
def index_knowledge_base(dir_path: Optional[str] = None) -> dict[str, Any]:
    """索引文档目录到知识库

    Args:
        dir_path: 文档目录路径，未提供则使用配置中的默认路径

    Returns:
        dict: 索引结果，包含索引的文档和分块数量
    """
    from pathlib import Path

    retriever = get_retriever()

    # 索引文档
    if dir_path:
        path = Path(dir_path)
    else:
        path = None

    chunk_count = retriever.index_directory(path)

    # 获取统计信息
    stats = retriever.get_stats()

    return {
        "success": True,
        "indexed_chunks": chunk_count,
        "total_chunks_in_store": stats["total_chunks"],
        "message": f"成功索引 {chunk_count} 个文档分块",
    }


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "get_knowledge_base_stats",
            "description": "获取知识库的统计信息，包括文档数量、向量维度等。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
)
def get_knowledge_base_stats() -> dict[str, Any]:
    """获取知识库统计信息

    Returns:
        dict: 知识库统计信息
    """
    retriever = get_retriever()
    return retriever.get_stats()


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "clear_knowledge_base",
            "description": "清空知识库中的所有索引数据。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
)
def clear_knowledge_base() -> dict[str, Any]:
    """清空知识库索引

    Returns:
        dict: 操作结果
    """
    retriever = get_retriever()
    retriever.clear_index()

    return {
        "success": True,
        "message": "知识库已清空",
    }


# 在模块导入时自动索引默认文档目录
def auto_index_default_documents() -> None:
    """自动索引默认文档目录

    如果默认文档目录存在且包含文件，则自动加载索引。
    这使得 Agent 启动后即可使用知识库，无需手动索引。
    """
    from pathlib import Path

    config = RAGConfig()
    data_dir = Path(config.data_dir)

    if not data_dir.exists():
        # 创建示例文档目录
        data_dir.mkdir(parents=True, exist_ok=True)
        print(f"创建知识库文档目录: {data_dir}")
        return

    # 检查目录中是否有文档
    txt_files = list(data_dir.glob("*.txt"))
    md_files = list(data_dir.glob("*.md"))

    if txt_files or md_files:
        print(f"自动索引知识库文档目录: {data_dir}")
        retriever = get_retriever(config)
        chunk_count = retriever.index_directory()
        print(f"已索引 {chunk_count} 个文档分块")
    else:
        print(f"知识库文档目录为空: {data_dir}")
        print("请添加 .txt 或 .md 文件后调用 index_knowledge_base 工具")


# 模块导入时不自动索引，让用户明确控制
# auto_index_default_documents()