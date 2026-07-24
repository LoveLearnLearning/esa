# backend/agent/rag/__init__.py
"""
RAG（检索增强生成）模块

该模块提供文档检索增强生成功能，支持：
- 文档加载与处理
- 文本分块与向量化
- 相似度检索
- 与 Agent 工具系统无缝集成

架构设计：
- base.py: 定义抽象接口（EmbeddingProvider, VectorStore）
- config.py: 配置参数管理
- document/: 文档加载与处理
- embeddings/: 向量化实现
- vectorstore/: 向量存储实现
- retriever.py: 检索逻辑
- rag_tool.py: Agent 工具注册
"""

from backend.agent.rag.config import RAGConfig
from backend.agent.rag.retriever import Retriever

__all__ = ["RAGConfig", "Retriever"]