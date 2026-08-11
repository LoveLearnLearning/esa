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
    DIRECT = "direct"
    RAG = "rag"


@dataclass(frozen=True)
class VisualAnalysis:
    description: str
    visible_text: str = ""
    content_type: str = "image"

    def as_text(self) -> str:
        parts = [f"视觉内容：{self.description.strip()}"]
        if self.visible_text.strip():
            parts.append(f"图中可见文字：{self.visible_text.strip()}")
        if self.content_type.strip():
            parts.append(f"视觉类型：{self.content_type.strip()}")
        return "\n".join(parts)


class VisionProvider(Protocol):
    provider_name: str
    model_name: str
    model_revision: str | None

    @property
    def configuration_fingerprint(self) -> str: ...

    async def analyze(
        self, image: bytes, media_type: str, prompt: str
    ) -> VisualAnalysis: ...


class TokenCounter(Protocol):
    model_name: str

    def count_tokens(self, text: str) -> int: ...


@dataclass(frozen=True)
class ParsedAttachment:
    document: Document
    document_root: Path


class DocumentParser(Protocol):
    configuration_fingerprint: str

    def parse(self, source: Path, document_root: Path) -> ParsedAttachment: ...


@dataclass
class PreparedAttachment:
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
        if self.mode is AttachmentMode.DIRECT:
            if self.direct_context is None:
                raise RuntimeError("direct attachment is missing its context")
            return self.direct_context
        if self.retrieval is None:
            raise RuntimeError("rag attachment is missing its retrieval service")
        return self.retrieval.search(query, context_level=context_level)
