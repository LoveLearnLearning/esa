# backend/agent/rag/embeddings/simple.py
"""
简单 Embedding 实现占位

使用哈希函数生成固定维度的向量作为占位实现。
不依赖外部模型，仅用于验证系统流程。

未来可替换为：
- BGE (BAAI/bge-small-zh)
- text2vec
- OpenAI Embedding API
"""

import hashlib
from typing import Any

from backend.agent.rag.base import EmbeddingProvider


class SimpleEmbedding(EmbeddingProvider):
    """简单 Embedding 提供者（占位实现）

    使用文本的哈希值生成固定维度的向量。
    注意：这不是真正的语义向量，仅用于占位测试。

    Attributes:
        dimension: 向量维度，默认 128
        normalize: 是否归一化向量，默认 True
    """

    def __init__(self, dimension: int = 128, normalize: bool = True):
        """初始化简单 Embedding 提供者

        Args:
            dimension: 向量维度，必须是正整数
            normalize: 是否将向量归一化到 [0, 1] 范围

        Raises:
            ValueError: dimension 不合法
        """
        if dimension <= 0:
            raise ValueError(f"dimension 必须大于 0，当前值: {dimension}")

        self.dimension = dimension
        self.normalize = normalize

    def embed(self, text: str) -> list[float]:
        """将文本转换为向量（占位实现）

        使用 SHA256 哈希生成种子，然后通过伪随机数生成向量。

        Args:
            text: 输入文本

        Returns:
            list[float]: 固定维度的向量
        """
        if not text:
            return [0.0] * self.dimension

        # 生成文本哈希作为种子
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        # 使用哈希的前 16 个字符作为种子
        seed = int(text_hash[:16], 16)

        # 伪随机数生成器
        vector = self._generate_vector_from_seed(seed)

        # 归一化（可选）
        if self.normalize:
            vector = self._normalize_vector(vector)

        return vector

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量文本向量化

        Args:
            texts: 文本列表

        Returns:
            list[list[float]]: 向量列表
        """
        return [self.embed(text) for text in texts]

    def get_dimension(self) -> int:
        """获取向量维度

        Returns:
            int: 向量维度
        """
        return self.dimension

    def _generate_vector_from_seed(self, seed: int) -> list[float]:
        """从种子生成向量

        使用简单的线性同余生成器（LCG）生成伪随机向量。

        Args:
            seed: 随机种子

        Returns:
            list[float]: 生成的向量
        """
        vector = []

        # LCG 参数（常见的参数组合）
        a = 1664525
        c = 1013904223
        m = 2**32

        current = seed

        for _ in range(self.dimension):
            current = (a * current + c) % m
            # 映射到 [0, 1] 范围
            value = current / m
            vector.append(value)

        return vector

    def _normalize_vector(self, vector: list[float]) -> list[float]:
        """归一化向量到 [0, 1] 范围

        Args:
            vector: 输入向量

        Returns:
            list[float]: 归一化后的向量
        """
        min_val = min(vector)
        max_val = max(vector)

        # 避免除以零
        if max_val == min_val:
            return [0.5] * len(vector)

        # 归一化到 [0, 1]
        return [(v - min_val) / (max_val - min_val) for v in vector]


class SimpleCosineSimilarity:
    """简单余弦相似度计算器

    提供向量之间的相似度计算功能。
    """

    @staticmethod
    def compute(vec1: list[float], vec2: list[float]) -> float:
        """计算两个向量的余弦相似度

        Args:
            vec1: 向量 1
            vec2: 向量 2

        Returns:
            float: 相似度值，范围 [-1, 1]

        Raises:
            ValueError: 向量长度不一致
        """
        if len(vec1) != len(vec2):
            raise ValueError(
                f"向量长度不一致: len(vec1)={len(vec1)}, "
                f"len(vec2)={len(vec2)}"
            )

        # 计算点积
        dot_product = sum(a * b for a, b in zip(vec1, vec2))

        # 计算模长
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5

        # 避免除以零
        if norm1 == 0 or norm2 == 0:
            return 0.0

        # 计算余弦相似度
        similarity = dot_product / (norm1 * norm2)

        # 确保在 [-1, 1] 范围内（处理浮点误差）
        return max(-1.0, min(1.0, similarity))