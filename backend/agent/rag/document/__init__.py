# backend/agent/rag/document/__init__.py
"""文档处理模块"""

from backend.agent.rag.document.loader import TextLoader
from backend.agent.rag.document.splitter import TextSplitter

__all__ = ["TextLoader", "TextSplitter"]