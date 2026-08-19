# backend/agent/mm/contracts.py

"""mm 模块的公开契约。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Protocol

from backend.agent.DocIR import Document
from backend.agent.rag.retrieval import RetrievalService
from backend.agent.rag.retrieval.contracts import ContextLevel, SearchResponse


class AttachmentMode(str, Enum):
    """封装 `AttachmentMode` 的状态与行为。"""
    DIRECT = "direct"
    RAG = "rag"


MM_VISUAL_CONTRACT_VERSION = "mm-visual-contract-0.3"


class VisualRoute(str, Enum):
    """视觉资产的确定性处理路线。"""

    SKIP_EXISTING_STRUCTURE = "skip_existing_structure"
    GENERIC_VLM = "generic_vlm"
    OCR = "ocr"
    SPECIALIST = "specialist"
    MANUAL_REVIEW = "manual_review"


class VisualRisk(str, Enum):
    """视觉结果的保守风险等级。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class VisualDecision(str, Enum):
    """视觉候选的无标签准入决定。"""

    ACCEPT = "accept"
    REVIEW = "review"
    REJECT = "reject"


@dataclass(frozen=True)
class VisualRouteDecision:
    """记录路由选择及其确定性理由。"""

    route: VisualRoute
    risk: VisualRisk
    reason: str
    should_analyze: bool


@dataclass(frozen=True)
class VisualEvidence:
    """记录一个可回查的视觉证据来源。"""

    kind: str
    source: str
    asset_id: str | None = None
    asset_sha256: str | None = None
    element_id: str | None = None
    locator_id: str | None = None
    confidence: float | None = None
    details: str = ""

    def __post_init__(self) -> None:
        if not self.kind.strip() or not self.source.strip():
            raise ValueError("visual evidence kind and source must be non-empty")
        if self.asset_sha256 is not None and (
            len(self.asset_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.asset_sha256)
        ):
            raise ValueError("visual evidence asset_sha256 must be a SHA-256 hex string")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("visual evidence confidence must be between 0 and 1")


@dataclass(frozen=True)
class VisualEnrichmentRequest:
    """MM adapter 的稳定输入契约。"""

    document_id: str
    element_id: str
    asset_id: str
    asset_sha256: str
    media_type: str
    asset_path: str
    source_type: str | None = None
    page_id: str | None = None
    locator_ids: tuple[str, ...] = ()
    caption: str = ""
    surrounding_text: str = ""
    ocr_text: str = ""
    existing_structure: str = ""
    route: VisualRoute = VisualRoute.GENERIC_VLM
    risk: VisualRisk = VisualRisk.UNKNOWN

    def __post_init__(self) -> None:
        for name in ("document_id", "element_id", "asset_id", "asset_sha256", "media_type", "asset_path"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if len(self.asset_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.asset_sha256
        ):
            raise ValueError("asset_sha256 must be a SHA-256 hex string")


@dataclass(frozen=True)
class VisualEnrichmentCandidate:
    """视觉 provider 或专项 adapter 的候选结果。"""

    description: str
    visible_text: str = ""
    content_type: str = "image"
    structure: Mapping[str, object] | None = None
    unresolved_items: tuple[str, ...] = ()
    evidence: tuple[VisualEvidence, ...] = ()
    validator_findings: tuple[str, ...] = ()
    provider_name: str | None = None
    model_name: str | None = None
    model_revision: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("visual candidate description must be non-empty")
        if not isinstance(self.visible_text, str):
            raise ValueError("visual candidate visible_text must be a string")
        if not isinstance(self.content_type, str) or not self.content_type.strip():
            raise ValueError("visual candidate content_type must be non-empty")
        if self.structure is not None:
            try:
                json.dumps(self.structure, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError) as exc:
                raise ValueError("visual candidate structure must be JSON serializable") from exc

    @classmethod
    def from_analysis(
        cls,
        analysis: "VisualAnalysis",
        *,
        provider_name: str | None = None,
        model_name: str | None = None,
        model_revision: str | None = None,
    ) -> "VisualEnrichmentCandidate":
        return cls(
            description=analysis.description,
            visible_text=analysis.visible_text,
            content_type=analysis.content_type,
            provider_name=provider_name,
            model_name=model_name,
            model_revision=model_revision,
        )

    def as_text(self) -> str:
        """Return the non-authoritative text representation used by MM."""
        parts = [f"视觉内容：{self.description.strip()}"]
        if self.visible_text.strip():
            parts.append(f"图中可见文字：{self.visible_text.strip()}")
        if self.content_type.strip():
            parts.append(f"视觉类型：{self.content_type.strip()}")
        return "\n".join(parts)


@dataclass(frozen=True)
class VisualEnrichmentOutcome:
    """记录候选的准入决定及可消费范围。"""

    request: VisualEnrichmentRequest
    route_decision: VisualRouteDecision
    decision: VisualDecision
    candidate: VisualEnrichmentCandidate | None = None
    reason: str = ""
    write_to_docir: bool = False
    retrieval_eligible: bool = False

    def __post_init__(self) -> None:
        if self.decision is VisualDecision.ACCEPT and self.candidate is None:
            raise ValueError("accepted visual outcome requires a candidate")
        if self.decision is not VisualDecision.ACCEPT and self.write_to_docir:
            raise ValueError("only accepted visual outcomes may write to DocIR")
        if self.decision is not VisualDecision.ACCEPT and self.retrieval_eligible:
            raise ValueError("only accepted visual outcomes may enter retrieval")


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
