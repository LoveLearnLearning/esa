# backend/agent/rag/embeddings/bge_embedding.py
"""
BGE Embedding 实现

使用 BAAI/bge-small-zh 模型生成中文语义向量。
这是行业标准的 Embedding 模型，具有真正的语义理解能力。
"""

import logging
from typing import Optional

from backend.agent.rag.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class BGEEmbedding(EmbeddingProvider):
    """BGE Embedding 提供者

    使用 BAAI/bge-small-zh 模型，专为中文语义理解设计。
    向量维度: 512

    Attributes:
        model_name: 模型名称
        dimension: 向量维度
        cache_folder: 模型缓存目录
        device: 运行设备（cuda/cpu）
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-zh",
        cache_folder: Optional[str] = None,
        device: str = None,
    ):
        """初始化 BGE Embedding

        Args:
            model_name: 模型名称，默认 BAAI/bge-small-zh
            cache_folder: 模型缓存目录，None 则使用默认
            device: 运行设备，None 则自动选择
        """
        self.model_name = model_name
        self.cache_folder = cache_folder
        self.device = device

        # 延迟加载模型（避免导入错误）
        self._model = None
        self._dimension = 512  # bge-small-zh 的维度

        logger.info(f"BGE Embedding 初始化: {model_name}")

    def _load_model(self):
        """延迟加载模型"""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                logger.info(f"正在加载模型: {self.model_name}")

                # 加载模型
                self._model = SentenceTransformer(
                    self.model_name,
                    cache_folder=self.cache_folder,
                    device=self.device,
                )

                # 更新实际维度
                self._dimension = self._model.get_sentence_embedding_dimension()

                logger.info(f"模型加载完成，向量维度: {self._dimension}")

            except ImportError as e:
                raise ImportError(
                    "请安装 sentence-transformers: pip install sentence-transformers"
                ) from e
            except Exception as e:
                logger.error(f"模型加载失败: {e}")
                raise

    def embed(self, text: str) -> list[float]:
        """将文本转换为向量

        Args:
            text: 输入文本

        Returns:
            list[float]: 语义向量
        """
        if not text or not text.strip():
            # 返回零向量
            return [0.0] * self._dimension

        # 确保模型已加载
        self._load_model()

        # 生成向量
        try:
            embedding = self._model.encode(
                text,
                normalize_embeddings=True,  # 归一化，便于余弦相似度计算
                show_progress_bar=False,
            )
            return embedding.tolist()
        except Exception as e:
            logger.error(f"向量化失败: {e}")
            raise

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量文本向量化

        Args:
            texts: 文本列表

        Returns:
            list[list[float]]: 向量列表
        """
        if not texts:
            return []

        # 确保模型已加载
        self._load_model()

        # 批量向量化
        try:
            embeddings = self._model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=len(texts) > 100,  # 大批量时显示进度
                batch_size=32,  # 批处理大小
            )
            return [emb.tolist() for emb in embeddings]
        except Exception as e:
            logger.error(f"批量向量化失败: {e}")
            raise

    def get_dimension(self) -> int:
        """获取向量维度

        Returns:
            int: 向量维度
        """
        return self._dimension

    def __repr__(self) -> str:
        return f"BGEEmbedding(model={self.model_name}, dimension={self._dimension})"