# backend/agent/rag/vectorstore/memory.py
"""
内存向量存储实现

使用 Python 列表在内存中存储向量，适合小规模数据测试。
未来可替换为 ChromaDB、FAISS 等。
"""

from typing import Any, Optional

from backend.agent.rag.base import DocumentChunk, RetrievalResult, VectorStore
from backend.agent.rag.embeddings.simple import SimpleCosineSimilarity


class MemoryVectorStore(VectorStore):
    """内存向量存储

    将向量和文档分块存储在内存中的简单实现。
    适合测试和小规模数据，不持久化。

    Attributes:
        chunks: 存储的文档分块列表
        vectors: 存储的向量列表
    """

    def __init__(self):
        """初始化内存向量存储"""
        self.chunks: list[DocumentChunk] = []
        self.vectors: list[list[float]] = []

    def add(self, chunks: list[DocumentChunk]) -> None:
        """添加文档分块到向量库

        Args:
            chunks: 文档分块列表，每个分块必须已包含 embedding

        Raises:
            ValueError: 分块缺少 embedding
        """
        for chunk in chunks:
            if chunk.embedding is None:
                raise ValueError(
                    f"分块 {chunk.chunk_id} 缺少 embedding，"
                    f"请先调用 embedding_provider.embed()"
                )

            self.chunks.append(chunk)
            self.vectors.append(chunk.embedding)

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        similarity_threshold: float = 0.0,
    ) -> list[RetrievalResult]:
        """根据向量检索相似文档

        Args:
            query_vector: 查询向量
            top_k: 返回的最大结果数
            similarity_threshold: 相似度阈值，低于此值的结果将被过滤

        Returns:
            list[RetrievalResult]: 检索结果列表，按相似度降序排列
        """
        if not self.vectors:
            return []

        # 计算所有向量与查询向量的相似度
        similarities: list[tuple[int, float]] = []

        for i, stored_vector in enumerate(self.vectors):
            try:
                similarity = SimpleCosineSimilarity.compute(
                    query_vector,
                    stored_vector,
                )
                similarities.append((i, similarity))
            except ValueError as e:
                # 记录错误但继续处理其他向量
                print(f"计算相似度失败 (索引 {i}): {e}")
                continue

        # 过滤低于阈值的结果
        filtered = [
            (idx, sim) for idx, sim in similarities
            if sim >= similarity_threshold
        ]

        # 按相似度降序排序
        sorted_results = sorted(
            filtered,
            key=lambda x: x[1],
            reverse=True,
        )

        # 取前 top_k 个结果
        top_results = sorted_results[:top_k]

        # 构建 RetrievalResult 列表
        results: list[RetrievalResult] = []

        for rank, (idx, score) in enumerate(top_results, start=1):
            result = RetrievalResult(
                chunk=self.chunks[idx],
                score=score,
                rank=rank,
            )
            results.append(result)

        return results

    def clear(self) -> None:
        """清空向量库"""
        self.chunks.clear()
        self.vectors.clear()

    def count(self) -> int:
        """获取向量库中的文档数量

        Returns:
            int: 文档数量
        """
        return len(self.chunks)

    def get_chunk_by_id(self, chunk_id: str) -> Optional[DocumentChunk]:
        """根据 ID 获取文档分块

        Args:
            chunk_id: 分块 ID

        Returns:
            Optional[DocumentChunk]: 找到的分块，未找到返回 None
        """
        for chunk in self.chunks:
            if chunk.chunk_id == chunk_id:
                return chunk
        return None

    def get_all_chunks(self) -> list[DocumentChunk]:
        """获取所有文档分块

        Returns:
            list[DocumentChunk]: 所有分块列表
        """
        return self.chunks.copy()