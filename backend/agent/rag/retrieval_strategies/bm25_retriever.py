# backend/agent/rag/retriever/bm25_retriever.py
"""
BM25 检索器实现

使用 BM25 算法进行关键词检索。
BM25 是经典的 TF-IDF 改进算法，适合精确关键词匹配。
"""

import logging
from typing import List, Optional

from backend.agent.rag.base import Document, DocumentChunk, RetrievalResult

logger = logging.getLogger(__name__)


class BM25Retriever:
    """BM25 检索器

    使用 Okapi BM25 算法进行关键词检索。

    Attributes:
        k1: BM25 参数，默认 1.5
        b: BM25 参数，默认 0.75
        epsilon: 平滑参数，默认 0.25
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        epsilon: float = 0.25,
    ):
        """初始化 BM25 检索器

        Args:
            k1: 词频饱和参数
            b: 文档长度归一化参数
            epsilon: 平滑参数
        """
        self.k1 = k1
        self.b = b
        self.epsilon = epsilon

        # 存储的分块和语料库
        self._chunks: List[DocumentChunk] = []
        self._corpus: List[List[str]] = []
        self._bm25 = None

        logger.info(f"BM25 检索器初始化: k1={k1}, b={b}")

    def _tokenize(self, text: str) -> List[str]:
        """简单的中文分词

        将文本按字符分割，过滤空白字符。

        Args:
            text: 输入文本

        Returns:
            List[str]: 分词结果
        """
        # 简单实现：按字符分割
        # 生产环境可以使用 jieba 等分词工具
        tokens = []
        for char in text:
            if char.strip():  # 过滤空白字符
                tokens.append(char)
        return tokens

    def add(self, chunks: List[DocumentChunk]) -> None:
        """添加文档分块

        Args:
            chunks: 文档分块列表
        """
        if not chunks:
            return

        # 延迟导入 rank_bm25
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            raise ImportError("请安装 rank_bm25: pip install rank_bm25")

        # 分词
        for chunk in chunks:
            tokens = self._tokenize(chunk.content)
            self._corpus.append(tokens)
            self._chunks.append(chunk)

        # 重建索引
        self._bm25 = BM25Okapi(self._corpus)

        logger.info(f"BM25 索引构建完成: {len(self._chunks)} 个文档")

    def search(
        self,
        query: str,
        top_k: int = 5,
        similarity_threshold: float = 0.0,
    ) -> List[RetrievalResult]:
        """检索相关文档

        Args:
            query: 查询文本
            top_k: 返回的最大结果数
            similarity_threshold: 相似度阈值

        Returns:
            List[RetrievalResult]: 检索结果列表
        """
        if not self._bm25 or not self._chunks:
            return []

        # 分词查询
        query_tokens = self._tokenize(query)

        # BM25 检索
        scores = self._bm25.get_scores(query_tokens)

        # 获取 top-k 结果
        top_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True,
        )[:top_k]

        # 转换为 RetrievalResult
        results: List[RetrievalResult] = []

        for rank, idx in enumerate(top_indices, start=1):
            score = float(scores[idx])

            # 过滤低于阈值的结果
            if score < similarity_threshold:
                continue

            result = RetrievalResult(
                chunk=self._chunks[idx],
                score=score,
                rank=rank,
            )
            results.append(result)

        return results

    def clear(self) -> None:
        """清空索引"""
        self._chunks.clear()
        self._corpus.clear()
        self._bm25 = None

        logger.info("BM25 索引已清空")

    def count(self) -> int:
        """获取文档数量

        Returns:
            int: 文档数量
        """
        return len(self._chunks)