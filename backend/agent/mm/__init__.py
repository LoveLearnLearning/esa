# backend/agent/mm/__init__.py

"""ESA 多模态附件摄取公共入口。"""

from .config import MMConfig
from .contracts import (
    AttachmentMode,
    DocumentParser,
    MM_VISUAL_CONTRACT_VERSION,
    ParsedAttachment,
    PreparedAttachment,
    TokenCounter,
    VisionProvider,
    VisualAnalysis,
    VisualDecision,
    VisualEnrichmentCandidate,
    VisualEnrichmentOutcome,
    VisualEnrichmentRequest,
    VisualEvidence,
    VisualRisk,
    VisualRoute,
    VisualRouteDecision,
)
from .enrichment import EnrichmentResult, enrich_visual_assets
from .providers import OpenAICompatibleVisionProvider, TransformersTokenCounter
from .render import render_document_markdown
from .routing import MM_VISUAL_ROUTING_VERSION, route_visual_element
from .selection import MM_VISUAL_SELECTION_VERSION, select_visual_candidate
from .service import MultimodalIngestionService
from .session import AttachmentPreparationStatus, MultimodalSessionService
from .visual import VisualEnrichmentService

__all__ = [
    "AttachmentMode",
    "AttachmentPreparationStatus",
    "DocumentParser",
    "EnrichmentResult",
    "MM_VISUAL_CONTRACT_VERSION",
    "MM_VISUAL_ROUTING_VERSION",
    "MM_VISUAL_SELECTION_VERSION",
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
    "VisualEnrichmentService",
    "VisualDecision",
    "VisualEnrichmentCandidate",
    "VisualEnrichmentOutcome",
    "VisualEnrichmentRequest",
    "VisualEvidence",
    "VisualRisk",
    "VisualRoute",
    "VisualRouteDecision",
    "enrich_visual_assets",
    "render_document_markdown",
    "route_visual_element",
    "select_visual_candidate",
]
