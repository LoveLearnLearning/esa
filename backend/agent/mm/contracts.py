# backend/agent/mm/contracts.py

"""mm 模块的公开契约。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from backend.agent.DocIR import Document
from backend.agent.rag.retrieval import RetrievalService
from backend.agent.rag.retrieval.contracts import ContextLevel, SearchResponse


class AttachmentMode(str, Enum):
    """封装 `AttachmentMode` 的状态与行为。"""
    DIRECT = "direct"
    RAG = "rag"


@dataclass(frozen=True)
class VisualAnalysis:
    """封装 `VisualAnalysis` 的状态与行为。"""
    description: str
    visible_text: str = ""
    content_type: str = "image"

    def as_text(self) -> str:
        """处理 `as_text` 相关逻辑。"""
        parts = [f"视觉内容：{self.description.strip()}"]
        if self.visible_text.strip():
            parts.append(f"图中可见文字：{self.visible_text.strip()}")
        if self.content_type.strip():
            parts.append(f"视觉类型：{self.content_type.strip()}")
        return "\n".join(parts)


class VisionProvider(Protocol):
    """定义 `VisionProvider` 组件协议。"""
    provider_name: str
    model_name: str
    model_revision: str | None

    @property
    def configuration_fingerprint(self) -> str:
        """处理 `configuration_fingerprint` 相关逻辑。"""
        ...

    async def analyze(
        self, image: bytes, media_type: str, prompt: str
    ) -> VisualAnalysis:
        """处理 `analyze` 相关逻辑。

        Args:
            image: bytes => `image` 参数。
            media_type: str => `media_type` 参数。
            prompt: str => `prompt` 参数。

        Returns:
            VisualAnalysis => 处理结果。
        """
        ...


class TokenCounter(Protocol):
    """定义 `TokenCounter` 组件协议。"""
    model_name: str

    def count_tokens(self, text: str) -> int:
        """统计 `tokens` 相关数据。"""
        ...


@dataclass(frozen=True)
class ParsedAttachment:
    """封装 `ParsedAttachment` 的状态与行为。"""
    document: Document
    document_root: Path


class DocumentParser(Protocol):
    """定义 `DocumentParser` 组件协议。"""
    configuration_fingerprint: str

    def parse(self, source: Path, document_root: Path) -> ParsedAttachment:
        """解析 `parse` 相关数据。

        Args:
            source: Path => `source` 参数。
            document_root: Path => `document_root` 参数。

        Returns:
            ParsedAttachment => 处理结果。
        """
        ...


@dataclass
class PreparedAttachment:
    """封装 `PreparedAttachment` 的状态与行为。"""
    source_path: Path
    document: Document
    mode: AttachmentMode
    token_count: int
    markdown_path: Path
    manifest_path: Path
    direct_context: str | None = None
    retrieval: RetrievalService | None = None

    def context_for(
        self, query: str, context_level: ContextLevel = ContextLevel.EVIDENCE
    ) -> str | SearchResponse:
        """处理 `context_for` 相关逻辑。

        Args:
            query: str => 查询文本。
            context_level: ContextLevel => `context_level` 参数。

        Returns:
            str | SearchResponse => 处理结果。
        """
        if self.mode is AttachmentMode.DIRECT:
            if self.direct_context is None:
                raise RuntimeError("direct attachment is missing its context")
            return self.direct_context
        if self.retrieval is None:
            raise RuntimeError("rag attachment is missing its retrieval service")
        return self.retrieval.search(query, context_level=context_level)
