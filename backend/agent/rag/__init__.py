# backend/agent/rag/__init__.py

"""
这个文件干什么：集中定义 ESA 第一阶段本地混合检索包的公共导入接口。

直白点说就是：其他代码要使用 RAG 时从这里统一拿功能，不必记住每个实现藏在哪个子目录。
"""

from .agent_api import (
    configure_retrieval_service,
    get_retrieval_service,
    knowledge_base_stats,
    retrieve_knowledge_payload,
)
from .collection import LoadedChunkCollection, load_chunk_collection
from .evaluation import EvaluationCase, RetrievalMetrics, evaluate_layers
from .indexes import QdrantIndex, ReferenceIndex
from .indexing import (
    IndexBuildResult,
    IndexDeployment,
    IndexGeneration,
    IndexingService,
    load_deployment,
)
from .inference import (
    HashingEmbeddingProvider,
    LexicalOverlapReranker,
    SentenceTransformersEmbeddingProvider,
    SentenceTransformersReranker,
    TransformersEmbeddingProvider,
    TransformersReranker,
    VLLMEmbeddingProvider,
    VLLMReranker,
)
from .retrieval.context import ContextBuilder, EvidenceAssembler
from .retrieval.contracts import ContextLevel, RetrievalConfig, SearchResponse
from .retrieval.reranking import CandidateReranker, CandidateSelection
from .retrieval.routing import RouteResult, RouteRetriever
from .retrieval.service import RetrievalService

__all__ = [
    "CandidateReranker",
    "CandidateSelection",
    "ContextBuilder",
    "ContextLevel",
    "EvaluationCase",
    "EvidenceAssembler",
    "HashingEmbeddingProvider",
    "IndexBuildResult",
    "IndexDeployment",
    "IndexGeneration",
    "IndexingService",
    "LexicalOverlapReranker",
    "LoadedChunkCollection",
    "QdrantIndex",
    "ReferenceIndex",
    "RetrievalConfig",
    "RetrievalMetrics",
    "RetrievalService",
    "RouteResult",
    "RouteRetriever",
    "SearchResponse",
    "SentenceTransformersEmbeddingProvider",
    "SentenceTransformersReranker",
    "TransformersEmbeddingProvider",
    "TransformersReranker",
    "VLLMEmbeddingProvider",
    "VLLMReranker",
    "configure_retrieval_service",
    "evaluate_layers",
    "get_retrieval_service",
    "knowledge_base_stats",
    "load_chunk_collection",
    "load_deployment",
    "retrieve_knowledge_payload",
]
