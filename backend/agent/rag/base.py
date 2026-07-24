# backend/agent/rag/base.py
"""
RAG 模块抽象接口定义

定义核心抽象类：
- EmbeddingProvider: Embedding 提供者接口
- VectorStore: 向量存储接口
- DocumentLoader: 文档加载器接口

使用 abc.ABC 定义抽象基类，确保子类必须实现关键方法。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class Document:
    """文档数据结构

    Attributes:
        content: 文档内容
        source: 来源文件名
        section: 章节信息（可选）
        page: 页码（可选）
        metadata: 其他元数据
    """

    content: str
    source: str
    section: Optional[str] = None
    page: Optional[int] = None
    metadata: dict[str, Any] = None

    def __post_init__(self):
        """初始化元数据"""
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "content": self.content,
            "source": self.source,
            "section": self.section,
            "page": self.page,
            "metadata": self.metadata,
        }


@dataclass
class DocumentChunk:
    """文档分块数据结构

    Attributes:
        content: 分块内容
        document: 所属文档
        chunk_id: 分块 ID
        start_idx: 在原文中的起始位置
        end_idx: 在原文中的结束位置
        embedding: 向量表示（可选）
    """

    content: str
    document: Document
    chunk_id: str
    start_idx: int
    end_idx: int
    embedding: Optional[list[float]] = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "content": self.content,
            "chunk_id": self.chunk_id,
            "source": self.document.source,
            "section": self.document.section,
            "page": self.document.page,
            "start_idx": self.start_idx,
            "end_idx": self.end_idx,
        }


@dataclass
class RetrievalResult:
    """检索结果数据结构

    Attributes:
        chunk: 文档分块
        score: 相似度得分
        rank: 排名
    """

    chunk: DocumentChunk
    score: float
    rank: int

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        result = {
            "content": self.chunk.content,
            "score": round(self.score, 4),
            "rank": self.rank,
            "source": self.chunk.document.source,
            "section": self.chunk.document.section,
            "page": self.chunk.document.page,
        }

        # 如果有额外元数据，也包含进来
        if self.chunk.document.metadata:
            result["metadata"] = self.chunk.document.metadata

        return result


class EmbeddingProvider(ABC):
    """Embedding 提供者抽象基类

    定义向量化接口，支持不同 Embedding 模型的插件化替换。
    """

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """将文本转换为向量

        Args:
            text: 输入文本

        Returns:
            list[float]: 文本的向量表示
        """
        pass

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量文本向量化

        Args:
            texts: 文本列表

        Returns:
            list[list[float]]: 向量列表
        """
        pass

    @abstractmethod
    def get_dimension(self) -> int:
        """获取向量维度

        Returns:
            int: 向量维度
        """
        pass


class VectorStore(ABC):
    """向量存储抽象基类

    定义向量存储与检索接口，支持不同向量数据库的插件化替换。
    """

    @abstractmethod
    def add(self, chunks: list[DocumentChunk]) -> None:
        """添加文档分块到向量库

        Args:
            chunks: 文档分块列表
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def clear(self) -> None:
        """清空向量库"""
        pass

    @abstractmethod
    def count(self) -> int:
        """获取向量库中的文档数量

        Returns:
            int: 文档数量
        """
        pass


class DocumentLoader(ABC):
    """文档加载器抽象基类

    定义文档加载接口，支持不同格式文档的加载。
    """

    @abstractmethod
    def load(self, file_path: Path) -> Document:
        """加载单个文档

        Args:
            file_path: 文档路径

        Returns:
            Document: 加载的文档对象
        """
        pass

    @abstractmethod
    def load_directory(self, dir_path: Path) -> list[Document]:
        """加载目录下所有文档

        Args:
            dir_path: 目录路径

        Returns:
            list[Document]: 文档列表
        """
        pass

    @abstractmethod
    def supports_format(self, file_extension: str) -> bool:
        """检查是否支持该文件格式

        Args:
            file_extension: 文件扩展名（如 '.txt'）

        Returns:
            bool: 是否支持
        """
        pass