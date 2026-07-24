# backend/agent/rag/retriever.py
"""
RAG 检索器实现

整合文档加载、分块、向量化和检索的完整流程。
支持混合检索（BM25 + 向量检索）和纯向量检索。
"""

from pathlib import Path
from typing import Any, Union, Optional

from backend.agent.rag.base import (
    Document,
    DocumentChunk,
    EmbeddingProvider,
    RetrievalResult,
    VectorStore,
)
from backend.agent.rag.config import RAGConfig
from backend.agent.rag.document.loader import TextLoader
from backend.agent.rag.document.splitter import TextSplitter
from backend.agent.rag.embeddings.simple import SimpleEmbedding
from backend.agent.rag.embeddings.bge_embedding import BGEEmbedding
from backend.agent.rag.vectorstore.memory import MemoryVectorStore
from backend.agent.rag.vectorstore.faiss_store import FAISSVectorStore
from backend.agent.rag.retrieval_strategies.hybrid_retriever import HybridRetriever


class Retriever:
    """RAG 检索器

    整合所有 RAG 组件，提供完整的检索增强生成流程：
    1. 加载文档
    2. 文本分块
    3. 向量化
    4. 存储到向量库
    5. 查询检索（支持混合检索）

    Attributes:
        config: RAG 配置
        loader: 文档加载器
        splitter: 文本分块器
        embedding_provider: Embedding 提供者
        vector_store: 向量存储
    """

    def __init__(
        self,
        config: Optional[RAGConfig] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        vector_store: Optional[VectorStore] = None,
    ):
        """初始化 RAG 检索器

        Args:
            config: RAG 配置，未提供则使用默认配置
            embedding_provider: Embedding 提供者，未提供则根据配置创建
            vector_store: 向量存储，未提供则根据配置创建
        """
        self.config = config or RAGConfig()

        # 初始化组件
        self.loader = TextLoader()
        self.splitter = TextSplitter(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
        )

        # 初始化 Embedding 提供者
        if embedding_provider:
            self.embedding_provider = embedding_provider
        else:
            self.embedding_provider = self._create_embedding_provider()

        # 初始化向量存储
        if vector_store:
            self.vector_store = vector_store
        else:
            self.vector_store = self._create_vector_store()

        # 初始化混合检索器（如果启用）
        self.hybrid_retriever: Optional[HybridRetriever] = None
        if self.config.use_hybrid:
            self.hybrid_retriever = HybridRetriever(
                embedding_provider=self.embedding_provider,
                bm25_weight=self.config.bm25_weight,
                vector_weight=self.config.vector_weight,
                rrf_k=self.config.rrf_k,
                vector_store_path=self.config.vector_store_path,
            )

    def _create_embedding_provider(self) -> EmbeddingProvider:
        """根据配置创建 Embedding 提供者"""
        if self.config.embedding_provider == "bge":
            return BGEEmbedding(
                model_name="BAAI/bge-small-zh",
            )
        else:
            return SimpleEmbedding()

    def _create_vector_store(self) -> VectorStore:
        """根据配置创建向量存储"""
        if self.config.vector_store_type == "faiss":
            return FAISSVectorStore(
                index_path=self.config.vector_store_path,
                dimension=self.embedding_provider.get_dimension(),
            )
        else:
            return MemoryVectorStore()

    def load_documents(self, dir_path: Optional[Union[str, Path]] = None) -> list[Document]:
        """加载文档目录

        Args:
            dir_path: 文档目录路径，未提供则使用配置中的 data_dir

        Returns:
            list[Document]: 加载的文档列表
        """
        dir_path = dir_path or self.config.data_dir
        return self.loader.load_directory(dir_path)

    def index_documents(self, documents: list[Document]) -> int:
        """索引文档（加载 → 分块 → 向量化 → 存储）

        Args:
            documents: 文档列表

        Returns:
            int: 索引的分块数量
        """
        if not documents:
            return 0

        # 分块
        chunks = self.splitter.split_documents(documents)

        # 如果启用混合检索，使用混合检索器
        if self.hybrid_retriever:
            self.hybrid_retriever.add(chunks)
        else:
            # 向量化
            for chunk in chunks:
                chunk.embedding = self.embedding_provider.embed(chunk.content)

            # 存储到向量库
            self.vector_store.add(chunks)

        return len(chunks)

    def index_directory(self, dir_path: Optional[Union[str, Path]] = None) -> int:
        """索引文档目录

        一步完成：加载 → 分块 → 向量化 → 存储

        Args:
            dir_path: 文档目录路径

        Returns:
            int: 索引的分块数量
        """
        documents = self.load_documents(dir_path)
        return self.index_documents(documents)

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        similarity_threshold: Optional[float] = None,
    ) -> list[RetrievalResult]:
        """检索相关文档

        Args:
            query: 查询文本
            top_k: 返回的最大结果数，未提供则使用配置
            similarity_threshold: 相似度阈值，未提供则使用配置

        Returns:
            list[RetrievalResult]: 检索结果列表
        """
        top_k = top_k or self.config.top_k
        similarity_threshold = similarity_threshold or self.config.similarity_threshold

        # 如果启用混合检索，使用混合检索器
        if self.hybrid_retriever:
            return self.hybrid_retriever.search(
                query=query,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
            )

        # 否则使用纯向量检索
        query_vector = self.embedding_provider.embed(query)

        results = self.vector_store.search(
            query_vector=query_vector,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )

        return results

    def retrieve_with_context(
        self,
        query: str,
        top_k: Optional[int] = None,
        similarity_threshold: Optional[float] = None,
    ) -> dict[str, Any]:
        """检索并返回完整上下文信息

        Args:
            query: 查询文本
            top_k: 返回的最大结果数
            similarity_threshold: 相似度阈值

        Returns:
            dict: 包含查询、结果、来源信息的完整上下文
        """
        results = self.retrieve(query, top_k, similarity_threshold)

        # 格式化来源信息（赛题要求：来源可追溯）
        sources = []

        for i, result in enumerate(results, start=1):
            chunk = result.chunk
            source_info = self.config.source_format.format(
                index=i,
                source_name=chunk.document.source,
                section=chunk.document.section or "未知章节",
                page=chunk.document.page or "未知",
            )
            sources.append(source_info)

        return {
            "query": query,
            "result_count": len(results),
            "results": [r.to_dict() for r in results],
            "sources": sources,
            "context_text": "\n\n".join(sources),
        }

    def clear_index(self) -> None:
        """清空向量库索引"""
        if self.hybrid_retriever:
            self.hybrid_retriever.clear()
        else:
            self.vector_store.clear()

    def save_index(self) -> None:
        """保存索引（FAISS 持久化）"""
        if self.hybrid_retriever:
            self.hybrid_retriever.save()
        elif hasattr(self.vector_store, 'save'):
            self.vector_store.save()

    def get_stats(self) -> dict[str, Any]:
        """获取检索器统计信息

        Returns:
            dict: 统计信息
        """
        return {
            "total_chunks": self.hybrid_retriever.count() if self.hybrid_retriever else self.vector_store.count(),
            "embedding_dimension": self.embedding_provider.get_dimension(),
            "use_hybrid": self.config.use_hybrid,
            "config": {
                "chunk_size": self.config.chunk_size,
                "chunk_overlap": self.config.chunk_overlap,
                "top_k": self.config.top_k,
                "similarity_threshold": self.config.similarity_threshold,
                "embedding_provider": self.config.embedding_provider,
                "vector_store_type": self.config.vector_store_type,
                "use_hybrid": self.config.use_hybrid,
                "bm25_weight": self.config.bm25_weight,
                "vector_weight": self.config.vector_weight,
            },
        }


# 全局检索器实例（单例模式）
_global_retriever: Optional[Retriever] = None


def get_retriever(config: Optional[RAGConfig] = None) -> Retriever:
    """获取全局检索器实例

    Args:
        config: RAG 配置，仅在首次创建时使用

    Returns:
        Retriever: 检索器实例
    """
    global _global_retriever

    if _global_retriever is None:
        _global_retriever = Retriever(config)

    return _global_retriever


def reset_retriever() -> None:
    """重置全局检索器"""
    global _global_retriever
    _global_retriever = None