# backend/agent/mm/__init__.py

"""ESA 多模态附件摄取公共入口。"""

from .config import MMConfig
from .contracts import (
    AttachmentMode,
    DocumentParser,
    ParsedAttachment,
    PreparedAttachment,
    TokenCounter,
    VisionProvider,
    VisualAnalysis,
)
from .enrichment import EnrichmentResult, enrich_visual_assets
from .providers import OpenAICompatibleVisionProvider, TransformersTokenCounter
from .render import render_document_markdown
from .service import MultimodalIngestionService
from .session import MultimodalSessionService

__all__ = [
    "AttachmentMode",
    "DocumentParser",
    "EnrichmentResult",
    "MMConfig",
    "MultimodalIngestionService",
    "MultimodalSessionService",
    "OpenAICompatibleVisionProvider",
    "ParsedAttachment",
    "PreparedAttachment",
    "TokenCounter",
    "TransformersTokenCounter",
    "VisionProvider",
    "VisualAnalysis",
    "enrich_visual_assets",
    "render_document_markdown",
]
