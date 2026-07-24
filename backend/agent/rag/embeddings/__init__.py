# backend/agent/rag/embeddings/__init__.py
"""Embedding 提供者模块"""

from backend.agent.rag.embeddings.simple import SimpleEmbedding
from backend.agent.rag.embeddings.bge_embedding import BGEEmbedding

__all__ = ["SimpleEmbedding", "BGEEmbedding"]