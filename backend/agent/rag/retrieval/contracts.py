# backend/agent/rag/retrieval/contracts.py

"""

这个文件干什么：定义第一阶段检索链稳定的数据契约、配置对象和可替换后端协议。

直白点说就是：先约定检索各环节收什么、返回什么，这样模型或索引换实现时主流程不用跟着重写。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Protocol

from ..chunk import Chunk, ContentRole


class ContextLevel(str, Enum):
    """命中证据向外扩展上下文的三个受控档位。"""

    EVIDENCE = "evidence"
    SECTION = "section"
    FULL_READ = "full_read"


@dataclass(frozen=True)
class RetrievalConfig:
    """Frozen production baseline; experiments must override fields explicitly."""

    dense_limit: int = 20
    bm25_body_limit: int = 20
    bm25_heading_limit: int = 20
    rrf_limit: int = 30
    rerank_limit: int = 20
    reranker_batch_size: int = 4
    final_limit: int = 5
    rrf_k: int = 60
    section_window: int = 1
    max_context_tokens: int = 8192
    rerank_threshold: float | None = None
    fusion_method: Literal["dense", "equal_rrf", "weighted_rrf", "score"] = "dense"
    dense_weight: float = 1.0
    lexical_body_weight: float = 0.75
    lexical_gate_enabled: bool = True
    reranker_enabled: bool = False
    reranker_prior_weight: float = 0.90

    def __post_init__(self) -> None:
        """拒绝非正候选数量、非正 RRF 常数和负章节窗口。"""

        positive_fields = (
            ("dense_limit", self.dense_limit),
            ("bm25_body_limit", self.bm25_body_limit),
            ("bm25_heading_limit", self.bm25_heading_limit),
            ("rrf_limit", self.rrf_limit),
            ("rerank_limit", self.rerank_limit),
            ("reranker_batch_size", self.reranker_batch_size),
            ("final_limit", self.final_limit),
            ("rrf_k", self.rrf_k),
            ("max_context_tokens", self.max_context_tokens),
        )
        for name, value in positive_fields:
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.section_window < 0:
            raise ValueError("section_window cannot be negative")
        unit_fields = (
            ("dense_weight", self.dense_weight),
            ("lexical_body_weight", self.lexical_body_weight),
            ("reranker_prior_weight", self.reranker_prior_weight),
        )
        for name, value in unit_fields:
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between zero and one")


@dataclass(frozen=True)
class RankedItem:
    """单个排名中的项目；score 的量纲由该排名所属阶段决定。"""

    chunk_id: str
    score: float


class EmbeddingProvider(Protocol):
    """定义嵌入后端最小接口，允许替换 vLLM、Transformers 或 ST。"""

    model_name: str

    @property
    def configuration_fingerprint(self) -> str:
        """返回影响向量内容的稳定配置指纹。"""

        ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """把一批文本编码为等维稠密向量。"""

        ...


class Reranker(Protocol):
    """重排后端最小接口，输入查询与候选文本并输出一一对应的分数。"""

    model_name: str

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        """为每个查询-文档组合返回一个相关性分数。"""

        ...


class RetrievalIndex(Protocol):
    """索引后端必须暴露三条彼此独立的召回路线。"""

    @property
    def configuration_fingerprint(self) -> str:
        """返回影响索引结构与排序语义的稳定配置指纹。"""

        ...

    def prepare(
        self,
        dense_dimension: int,
        generation_id: str,
        expected_count: int,
    ) -> None:
        """创建或校验索引容器，并拒绝混合不同代次。"""

        ...

    def generation_is_ready(
        self,
        generation_id: str,
        expected_count: int,
    ) -> bool:
        """确认索引只包含指定代次的完整数据。"""

        ...

    def build(
        self,
        chunks: Sequence[Chunk],
        dense_vectors: Sequence[Sequence[float]],
        *,
        generation_id: str,
    ) -> None:
        """使用 Chunk 与对应 Dense 向量构建完整索引。"""

        ...

    def dense(
        self,
        query_vector: Sequence[float],
        limit: int,
        content_roles: frozenset[ContentRole] | None = None,
    ) -> list[RankedItem]:
        """执行 Dense 向量召回。"""

        ...

    def bm25_body(
        self,
        query: str,
        limit: int,
        content_roles: frozenset[ContentRole] | None = None,
    ) -> list[RankedItem]:
        """执行正文 BM25 召回。"""

        ...

    def bm25_heading(
        self,
        query: str,
        limit: int,
        content_roles: frozenset[ContentRole] | None = None,
    ) -> list[RankedItem]:
        """执行标题和章节路径 BM25 召回。"""

        ...


@dataclass(frozen=True)
class Evidence:
    """检索证据及其可回查引用；quote_eligible 明确区分可检索与可引用。"""

    evidence_id: str
    chunk_id: str
    element_id: str
    text_layer_id: str | None
    text_start: int | None
    text_end: int | None
    evidence_text: str
    text_origin: str
    quote_eligible: bool
    derivation: str
    quality_issue_ids: tuple[str, ...]
    document_id: str
    source_version_id: str
    parse_revision_id: str
    document_name: str
    section_path: tuple[str, ...]
    locators: tuple[Mapping[str, object], ...]
    asset_ids: tuple[str, ...]


@dataclass(frozen=True)
class SearchHit:
    """表示一个最终命中及其分层分数、引用和章节上下文。"""

    chunk_id: str
    rrf_score: float
    rerank_score: float | None
    evidence: tuple[Evidence, ...]
    context_chunk_ids: tuple[str, ...]
    context_text: str


@dataclass(frozen=True)
class SearchTrace:
    """保留各层排序和降级状态，供分层评测与故障诊断使用。"""

    rankings: Mapping[str, tuple[str, ...]]
    degraded: tuple[str, ...] = field(default_factory=tuple)
    raw_scores: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    fusion: Mapping[str, float | str | bool] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResponse:
    """表示一次检索返回的命中集合、上下文档位和运行轨迹。"""

    query: str
    context_level: ContextLevel
    hits: tuple[SearchHit, ...]
    trace: SearchTrace
