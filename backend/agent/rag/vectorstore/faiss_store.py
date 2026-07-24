# backend/agent/rag/vectorstore/faiss_store.py
"""
FAISS 向量存储实现

使用 Facebook AI Similarity Search (FAISS) 进行高效向量检索。
支持持久化存储，适合生产环境。
"""

import logging
import pickle
from pathlib import Path
from typing import Optional, Union

import numpy as np

from backend.agent.rag.base import DocumentChunk, RetrievalResult, VectorStore

logger = logging.getLogger(__name__)


class FAISSVectorStore(VectorStore):
    """FAISS 向量存储

    使用 FAISS 进行高效的向量检索，支持：
    - L2 距离和内积相似度
    - 持久化存储
    - 高效的批量检索

    Attributes:
        index_path: 索引文件路径
        dimension: 向量维度
        metric: 距离度量方式（L2/IP）
    """

    def __init__(
        self,
        index_path: Union[str, Path] = "data/faiss_index",
        dimension: int = 512,
        metric: str = "L2",  # L2 或 IP (内积)
    ):
        """初始化 FAISS 向量存储

        Args:
            index_path: 索引文件路径
            dimension: 向量维度
            metric: 距离度量方式，L2 或 IP
        """
        self.index_path = Path(index_path)
        self.dimension = dimension
        self.metric = metric

        # 存储
        self._index = None
        self._chunks: list[DocumentChunk] = []
        self._vectors: list[list[float]] = []

        # 延迟导入 FAISS
        self._faiss = None

        # 尝试加载已有索引
        self._load_if_exists()

        logger.info(
            f"FAISS VectorStore 初始化: dimension={dimension}, metric={metric}"
        )

    def _import_faiss(self):
        """延迟导入 FAISS"""
        if self._faiss is None:
            try:
                import faiss

                self._faiss = faiss
                logger.info("FAISS 库加载成功")
            except ImportError:
                raise ImportError(
                    "请安装 faiss-cpu: pip install faiss-cpu\n"
                    "或 faiss-gpu: pip install faiss-gpu"
                )

    def _load_if_exists(self):
        """如果存在索引文件，则加载"""
        index_file = self.index_path / "index.faiss"
        meta_file = self.index_path / "metadata.pkl"

        if index_file.exists() and meta_file.exists():
            try:
                self._import_faiss()

                # 加载 FAISS 索引
                self._index = self._faiss.read_index(str(index_file))

                # 加载元数据
                with open(meta_file, "rb") as f:
                    data = pickle.load(f)
                    self._chunks = data.get("chunks", [])
                    self._vectors = data.get("vectors", [])

                logger.info(f"已加载现有索引: {len(self._chunks)} 个向量")

            except Exception as e:
                logger.warning(f"加载索引失败: {e}，将创建新索引")
                self._index = None
                self._chunks = []
                self._vectors = []

    def _create_index(self):
        """创建新的 FAISS 索引"""
        self._import_faiss()

        if self.metric == "L2":
            # L2 距离索引
            self._index = self._faiss.IndexFlatL2(self.dimension)
        else:
            # 内积索引（需要向量已归一化）
            self._index = self._faiss.IndexFlatIP(self.dimension)

        logger.info(f"创建新索引: metric={self.metric}, dimension={self.dimension}")

    def add(self, chunks: list[DocumentChunk]) -> None:
        """添加文档分块到向量库

        Args:
            chunks: 文档分块列表，每个分块必须已包含 embedding

        Raises:
            ValueError: 分块缺少 embedding 或维度不匹配
        """
        if not chunks:
            return

        # 确保索引存在
        if self._index is None:
            self._create_index()

        # 验证并添加向量
        vectors_to_add = []

        for chunk in chunks:
            if chunk.embedding is None:
                raise ValueError(
                    f"分块 {chunk.chunk_id} 缺少 embedding，"
                    f"请先调用 embedding_provider.embed()"
                )

            if len(chunk.embedding) != self.dimension:
                raise ValueError(
                    f"向量维度不匹配: 期望 {self.dimension}, "
                    f"实际 {len(chunk.embedding)}"
                )

            vectors_to_add.append(chunk.embedding)
            self._chunks.append(chunk)
            self._vectors.append(chunk.embedding)

        # 批量添加到 FAISS 索引
        vectors_array = np.array(vectors_to_add, dtype=np.float32)
        self._index.add(vectors_array)

        logger.info(f"添加 {len(chunks)} 个向量，总计 {len(self._chunks)} 个")

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
            similarity_threshold: 相似度阈值

        Returns:
            list[RetrievalResult]: 检索结果列表
        """
        if self._index is None or len(self._chunks) == 0:
            return []

        if len(query_vector) != self.dimension:
            logger.error(
                f"查询向量维度不匹配: 期望 {self.dimension}, "
                f"实际 {len(query_vector)}"
            )
            return []

        # 准备查询向量
        query_array = np.array([query_vector], dtype=np.float32)

        # FAISS 检索
        distances, indices = self._index.search(query_array, min(top_k, len(self._chunks)))

        # 转换为 RetrievalResult
        results: list[RetrievalResult] = []

        for rank, (idx, distance) in enumerate(zip(indices[0], distances[0]), start=1):
            if idx < 0 or idx >= len(self._chunks):
                continue

            # 将距离转换为相似度分数
            # L2 距离: 分数 = 1 / (1 + distance)
            # IP (内积): 分数 = distance (假设向量已归一化)
            if self.metric == "L2":
                score = 1.0 / (1.0 + distance)
            else:
                score = float(distance)

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

    def save(self) -> None:
        """保存索引到磁盘"""
        if self._index is None:
            logger.warning("索引为空，跳过保存")
            return

        # 创建目录
        self.index_path.mkdir(parents=True, exist_ok=True)

        # 保存 FAISS 索引
        index_file = self.index_path / "index.faiss"
        self._faiss.write_index(self._index, str(index_file))

        # 保存元数据
        meta_file = self.index_path / "metadata.pkl"
        with open(meta_file, "wb") as f:
            pickle.dump(
                {
                    "chunks": self._chunks,
                    "vectors": self._vectors,
                    "dimension": self.dimension,
                    "metric": self.metric,
                },
                f,
            )

        logger.info(f"索引已保存: {self.index_path}")

    def clear(self) -> None:
        """清空向量库"""
        self._chunks.clear()
        self._vectors.clear()
        self._index = None

        # 删除磁盘文件
        if self.index_path.exists():
            import shutil

            shutil.rmtree(self.index_path)

        logger.info("向量库已清空")

    def count(self) -> int:
        """获取向量库中的文档数量

        Returns:
            int: 文档数量
        """
        return len(self._chunks)

    def get_chunk_by_id(self, chunk_id: str) -> Optional[DocumentChunk]:
        """根据 ID 获取文档分块

        Args:
            chunk_id: 分块 ID

        Returns:
            Optional[DocumentChunk]: 找到的分块
        """
        for chunk in self._chunks:
            if chunk.chunk_id == chunk_id:
                return chunk
        return None