# backend/agent/rag/inference/__init__.py

"""

这个文件干什么：本地推理后端公共入口。

直白点说就是：把各种 Embedding 和 Reranker 实现集中放到一个公共入口。

本地推理后端公共入口。
"""

from .errors import InferenceUnavailable
from .http import VLLMEmbeddingProvider, VLLMReranker
from .reference import HashingEmbeddingProvider, LexicalOverlapReranker
from .sentence_transformers import (
    SentenceTransformersEmbeddingProvider,
    SentenceTransformersReranker,
)
from .transformers import TransformersEmbeddingProvider, TransformersReranker

__all__ = [
    "HashingEmbeddingProvider",
    "InferenceUnavailable",
    "LexicalOverlapReranker",
    "SentenceTransformersEmbeddingProvider",
    "SentenceTransformersReranker",
    "TransformersEmbeddingProvider",
    "TransformersReranker",
    "VLLMEmbeddingProvider",
    "VLLMReranker",
]
