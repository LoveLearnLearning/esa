# backend/agent/rag/config.py
"""
RAG 模块配置管理

使用 dataclass 定义配置参数，支持：
- 文本分块参数
- 检索参数
- 相似度阈值
- 来源元数据格式
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Union, Optional


@dataclass
class RAGConfig:
    """RAG 模块配置类

    Attributes:
        chunk_size: 文本分块大小（字符数）
        chunk_overlap: 分块重叠大小（字符数）
        top_k: 检索返回的最相似文档数量
        similarity_threshold: 相似度阈值，低于此值的结果将被过滤
        embedding_provider: Embedding 提供者类型
        vector_store_type: 向量存储类型
        data_dir: 数据目录路径
        source_format: 来源信息格式化模板

        # 混合检索配置
        use_hybrid: 是否使用混合检索
        bm25_weight: BM25 权重
        vector_weight: 向量检索权重
        rrf_k: RRF 参数
    """

    # 文本分块参数
    chunk_size: int = 500
    chunk_overlap: int = 100

    # 检索参数
    top_k: int = 5
    similarity_threshold: float = 0.5

    # Embedding 配置
    embedding_provider: Literal["simple", "bge", "openai"] = "bge"  # 默认改为 bge

    # 向量存储配置
    vector_store_type: Literal["memory", "faiss"] = "faiss"  # 默认改为 faiss

    # 数据路径
    data_dir: Union[str, Path] = field(
        default_factory=lambda: Path(__file__).resolve().parent / "sample_docs"
    )

    # 来源格式化
    source_format: str = "【来源 {index}】{source_name} · {section} · 第{page}页"

    # 模型路径（用于未来替换为专业模型）
    embedding_model_path: Optional[str] = None

    # 混合检索配置
    use_hybrid: bool = True  # 默认启用混合检索
    bm25_weight: float = 0.5
    vector_weight: float = 0.5
    rrf_k: int = 60

    # BM25 参数
    bm25_k1: float = 1.5
    bm25_b: float = 0.75

    # 向量存储路径
    vector_store_path: str = "data/faiss_index"

    def __post_init__(self):
        """参数校验"""
        if self.chunk_size <= 0:
            raise ValueError(f"chunk_size 必须大于 0，当前值: {self.chunk_size}")

        if self.chunk_overlap < 0:
            raise ValueError(
                f"chunk_overlap 不能为负数，当前值: {self.chunk_overlap}"
            )

        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) "
                f"必须小于 chunk_size ({self.chunk_size})"
            )

        if self.top_k <= 0:
            raise ValueError(f"top_k 必须大于 0，当前值: {self.top_k}")

        if not 0 <= self.similarity_threshold <= 1:
            raise ValueError(
                f"similarity_threshold 必须在 [0, 1] 范围内，"
                f"当前值: {self.similarity_threshold}"
            )

        # 转换路径为 Path 对象
        self.data_dir = Path(self.data_dir)