"""DocIR 视觉资产补全的文件内应用服务。"""

from __future__ import annotations

from pathlib import Path

from backend.agent.DocIR import Document

from ..contracts import VisionProvider
from ..enrichment import EnrichmentResult, enrich_visual_assets


class VisualEnrichmentService:
    """把 DocIR 视觉资产交给路由、VLM 和准入管线。"""

    def __init__(self, provider: VisionProvider, *, max_concurrency: int) -> None:
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        self.provider = provider
        self.max_concurrency = max_concurrency

    async def enrich(
        self,
        document: Document,
        document_root: Path,
    ) -> EnrichmentResult:
        """对一个已完成 MinerU/DocIR 的文档执行视觉补全。"""
        return await enrich_visual_assets(
            document,
            document_root,
            self.provider,
            max_concurrency=self.max_concurrency,
        )
