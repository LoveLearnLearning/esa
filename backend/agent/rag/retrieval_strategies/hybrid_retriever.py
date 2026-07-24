# backend/agent/rag/retrieval_strategies/hybrid_retriever.py
"""
混合检索器实现

结合 BM25 关键词检索和向量检索，使用 RRF (Reciprocal Rank Fusion) 融合结果。
"""

import logging
from typing import List, Optional

from backend.agent.rag.base import Document, DocumentChunk, EmbeddingProvider, RetrievalResult
from backend.agent.rag.retrieval_strategies.bm25_retriever import BM25Retriever
from backend.agent.rag.vectorstore.faiss_store import FAISSVectorStore

logger = logging.getLogger(__name__)


class HybridRetriever:
    """混合检索器

    结合 BM25 和向量检索的优势：
    - BM25: 精确关键词匹配
    - 向量检索: 语义相似性

    使用 RRF (Reciprocal Rank Fusion) 算法融合结果。

    Attributes:
        bm25_weight: BM25 权重，默认 0.5
        vector_weight: 向量检索权重，默认 0.5
        rrf_k: RRF 参数，默认 60
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        bm25_weight: float = 0.5,
        vector_weight: float = 0.5,
        rrf_k: int = 60,
        vector_store_path: str = "data/faiss_index",
    ):
        """初始化混合检索器

        Args:
            embedding_provider: Embedding 提供者
            bm25_weight: BM25 结果权重
            vector_weight: 向量检索结果权重
            rrf_k: RRF 算法参数
            vector_store_path: 向量存储路径
        """
        self.embedding_provider = embedding_provider
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.rrf_k = rrf_k

        # 初始化两个检索器
        self.bm25_retriever = BM25Retriever()
        self.vector_store = FAISSVectorStore(
            index_path=vector_store_path,
            dimension=embedding_provider.get_dimension(),
        )

        # 分块缓存
        self._chunks: List[DocumentChunk] = []

        logger.info(
            f"混合检索器初始化: bm25_weight={bm25_weight}, "
            f"vector_weight={vector_weight}, rrf_k={rrf_k}"
        )

    def add(self, chunks: List[DocumentChunk]) -> None:
        """添加文档分块到索引

        Args:
            chunks: 文档分块列表
        """
        if not chunks:
            return

        # 向量化
        for chunk in chunks:
            chunk.embedding = self.embedding_provider.embed(chunk.content)

        # 添加到 BM25 索引
        self.bm25_retriever.add(chunks)

        # 添加到向量存储
        self.vector_store.add(chunks)

        # 缓存
        self._chunks.extend(chunks)

        logger.info(f"混合检索器添加 {len(chunks)} 个分块，总计 {len(self._chunks)} 个")

    def search(
        self,
        query: str,
        top_k: int = 5,
        similarity_threshold: float = 0.0,
        bm25_top_k: Optional[int] = None,
        vector_top_k: Optional[int] = None,
    ) -> List[RetrievalResult]:
        """混合检索

        Args:
            query: 查询文本
            top_k: 返回的最大结果数
            similarity_threshold: 相似度阈值
            bm25_top_k: BM25 返回的结果数，默认 top_k * 2
            vector_top_k: 向量检索返回的结果数，默认 top_k * 2

        Returns:
            List[RetrievalResult]: 融合后的检索结果
        """
        if not self._chunks:
            return []

        # 设置各检索器的 top_k
        bm25_top_k = bm25_top_k or top_k * 2
        vector_top_k = vector_top_k or top_k * 2

        # 1. BM25 检索
        bm25_results = self.bm25_retriever.search(query, top_k=bm25_top_k)

        # 2. 向量检索
        query_vector = self.embedding_provider.embed(query)
        vector_results = self.vector_store.search(
            query_vector=query_vector,
            top_k=vector_top_k,
        )

        # 3. RRF 融合
        fused_results = self._rrf_fusion(
            bm25_results=bm25_results,
            vector_results=vector_results,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )

        return fused_results

    def _rrf_fusion(
        self,
        bm25_results: List[RetrievalResult],
        vector_results: List[RetrievalResult],
        top_k: int,
        similarity_threshold: float,
    ) -> List[RetrievalResult]:
        """RRF 融合算法

        Reciprocal Rank Fusion:
        RRF_score = sum(1 / (k + rank)) for each result list

        Args:
            bm25_results: BM25 检索结果
            vector_results: 向量检索结果
            top_k: 返回的最大结果数
            similarity_threshold: 相似度阈值

        Returns:
            List[RetrievalResult]: 融合后的结果
        """
        # 分块 ID -> RRF 分数
        chunk_scores = {}

        # 计算 BM25 分数贡献
        for result in bm25_results:
            chunk_id = result.chunk.chunk_id
            rrf_score = self.bm25_weight / (self.rrf_k + result.rank)
            chunk_scores[chunk_id] = chunk_scores.get(chunk_id, 0) + rrf_score

        # 计算向量检索分数贡献
        for result in vector_results:
            chunk_id = result.chunk.chunk_id
            rrf_score = self.vector_weight / (self.rrf_k + result.rank)
            chunk_scores[chunk_id] = chunk_scores.get(chunk_id, 0) + rrf_score

        # 按分数排序
        sorted_chunks = sorted(
            chunk_scores.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        # 构建 RetrievalResult
        results: List[RetrievalResult] = []
        chunk_map = {c.chunk_id: c for c in self._chunks}

        for rank, (chunk_id, score) in enumerate(sorted_chunks, start=1):
            if chunk_id not in chunk_map:
                continue

            # 归一化分数到 [0, 1]
            normalized_score = min(1.0, score / (self.bm25_weight + self.vector_weight) * 2)

            # 过滤低于阈值的结果
            if normalized_score < similarity_threshold:
                continue

            result = RetrievalResult(
                chunk=chunk_map[chunk_id],
                score=normalized_score,
                rank=rank,
            )
            results.append(result)

            if len(results) >= top_k:
                break

        return results

    def save(self) -> None:
        """保存索引"""
        self.vector_store.save()
        logger.info("混合检索器索引已保存")

    def clear(self) -> None:
        """清空索引"""
        self.bm25_retriever.clear()
        self.vector_store.clear()
        self._chunks.clear()
        logger.info("混合检索器索引已清空")

    def count(self) -> int:
        """获取文档数量

        Returns:
            int: 文档数量
        """
        return len(self._chunks)