# backend/agent/mm/service.py

"""多模态附件从源文件到 direct/RAG handle 的主编排。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from backend.agent.DocIR import load_document, save_document
from backend.agent.DocIR.tools.batch_corpus import SUPPORTED_SOURCE_SUFFIXES
from backend.agent.rag.chunk import ChunkConfig
from backend.agent.rag.chunk.cli import build_collection
from backend.agent.rag.chunk.serializer import file_sha256
from backend.agent.rag.collection import load_chunk_collection
from backend.agent.rag.indexing import IndexingService
from backend.agent.rag.inference import SentenceTransformersEmbeddingProvider
from backend.agent.rag.retrieval import RetrievalConfig, RetrievalService

from .config import MMConfig
from .contracts import (
    AttachmentMode,
    DocumentParser,
    MM_VISUAL_CONTRACT_VERSION,
    PreparedAttachment,
    TokenCounter,
    VisionProvider,
)
from .enrichment import VLM_DESCRIPTION_PROMPT, enrich_visual_assets
from .routing import MM_VISUAL_ROUTING_VERSION
from .selection import MM_VISUAL_SELECTION_VERSION
from .index import InMemoryAttachmentIndex
from .parser import MinerUDocumentParser
from .providers import OpenAICompatibleVisionProvider, TransformersTokenCounter
from .render import render_document_markdown
from backend.core.log.logger import get_pipeline_logger


logger = get_pipeline_logger("MM", __name__)
rag_logger = get_pipeline_logger("RAG", __name__)


def _canonical_sha256(value: object) -> str:
    """处理 `_canonical_sha256` 相关逻辑。"""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _atomic_json(path: Path, payload: object) -> None:
    """处理 `_atomic_json` 相关逻辑。"""
    _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _atomic_text(path: Path, value: str) -> None:
    """处理 `_atomic_text` 相关逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


class MultimodalIngestionService:
    """逐文件构建持久 DocIR 工件与进程内附件上下文。"""

    def __init__(
        self,
        config: MMConfig | None = None,
        *,
        parser: DocumentParser | None = None,
        vision: VisionProvider | None = None,
        token_counter: TokenCounter | None = None,
        embedding: Any | None = None,
        chunk_config: ChunkConfig | None = None,
        retrieval_config: RetrievalConfig | None = None,
    ) -> None:
        """初始化 `MultimodalIngestionService` 实例。"""
        self.config = config or MMConfig.from_env()
        self.parser = parser or MinerUDocumentParser(
            command=self.config.mineru_command,
            timeout_seconds=self.config.mineru_timeout_seconds,
            attempts=self.config.mineru_attempts,
            api_url=self.config.mineru_api_url,
        )
        self.vision = vision or OpenAICompatibleVisionProvider(
            base_url=self.config.vlm_base_url,
            model_name=self.config.vlm_model,
            model_revision=self.config.vlm_model_revision,
            api_key=self.config.vlm_api_key,
            timeout=self.config.vlm_timeout_seconds,
            attempts=self.config.vlm_attempts,
        )
        self.token_counter = token_counter or TransformersTokenCounter(
            self.config.tokenizer_path
        )
        self.embedding = embedding or SentenceTransformersEmbeddingProvider(
            self.config.embedding_model,
            self.config.embedding_device,
        )
        self.chunk_config = chunk_config or ChunkConfig()
        self.retrieval_config = retrieval_config or RetrievalConfig()

    async def prepare_files(
        self, paths: list[Path] | tuple[Path, ...]
    ) -> tuple[PreparedAttachment, ...]:
        """按输入顺序逐文件独立摄取和路由。"""

        if not paths:
            raise ValueError("at least one attachment is required")
        prepared = []
        for path in paths:
            prepared.append(await self.prepare_file(Path(path)))
        return tuple(prepared)

    async def prepare_file(self, source: Path) -> PreparedAttachment:
        """准备 `file` 相关数据。

        Args:
            source: Path => `source` 参数。

        Returns:
            PreparedAttachment => 处理结果。
        """
        started = time.monotonic()
        source = Path(source).resolve(strict=True)
        if not source.is_file():
            raise FileNotFoundError(source)
        if source.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
            raise ValueError(f"unsupported attachment type: {source.suffix}")
        source_sha256 = file_sha256(source)
        pipeline_fingerprint = self._pipeline_fingerprint()
        run_root = (
            self.config.artifact_root / source_sha256 / pipeline_fingerprint[:24]
        )
        document_root = run_root / "docir" / "document"
        document_path = document_root / "document.json"
        markdown_path = run_root / "document.md"
        manifest_path = run_root / "manifest.json"
        run_root.mkdir(parents=True, exist_ok=True)
        logger.info(
            "attachment ingestion started source=%s sha256=%s",
            source.name,
            source_sha256,
        )
        try:
            cached = self._load_cache(
                manifest_path,
                document_path,
                markdown_path,
                source_sha256,
                pipeline_fingerprint,
            )
            if cached is None:
                # MinerU 自身管理独立子进程和超时。这里保持调用同步，避免为一次
                # 长生命周期解析额外遗留线程；上层若需并发应使用任务进程隔离。
                parsed = await asyncio.to_thread(
                    self.parser.parse,
                    source,
                    document_root,
                )
                logger.info(
                    "visual enrichment started document_id=%s document_assets=%d",
                    parsed.document.document_id,
                    len(parsed.document.assets),
                )
                enrichment = await enrich_visual_assets(
                    parsed.document,
                    parsed.document_root,
                    self.vision,
                    max_concurrency=self.config.vlm_max_concurrency,
                )
                document = enrichment.document
                save_document(document, document_path)
                markdown = render_document_markdown(document)
                _atomic_text(markdown_path, markdown)
                token_count = await asyncio.to_thread(
                    self.token_counter.count_tokens,
                    markdown,
                )
                mode = self._route(token_count)
                logger.info(
                    "attachment routed mode=%s token_count=%d visual_assets=%d visual_failures=%d",
                    mode.value,
                    token_count,
                    enrichment.analyzed_assets,
                    len(enrichment.failed_assets),
                )
                manifest = {
                    "schema_version": "mm-run-0.2",
                    "status": "success",
                    "source": {
                        "filename": source.name,
                        "sha256": source_sha256,
                        "byte_size": source.stat().st_size,
                    },
                    "pipeline_fingerprint": pipeline_fingerprint,
                    "document_id": document.document_id,
                    "document_sha256": file_sha256(document_path),
                    "markdown_sha256": file_sha256(markdown_path),
                    "token_count": token_count,
                    "direct_context_token_limit": (
                        self.config.direct_context_token_limit
                    ),
                    "mode": mode.value,
                    "vlm": {
                        "analyzed_assets": enrichment.analyzed_assets,
                        "failed_asset_ids": list(enrichment.failed_assets),
                        "review_asset_ids": list(enrichment.reviewed_assets),
                        "rejected_asset_ids": list(enrichment.rejected_assets),
                        "outcomes": [
                            {
                                "asset_id": outcome.request.asset_id,
                                "element_id": outcome.request.element_id,
                                "route": outcome.route_decision.route.value,
                                "risk": outcome.route_decision.risk.value,
                                "decision": outcome.decision.value,
                                "reason": outcome.reason,
                            }
                            for outcome in enrichment.outcomes
                        ],
                        "contract_version": MM_VISUAL_CONTRACT_VERSION,
                        "routing_version": MM_VISUAL_ROUTING_VERSION,
                        "selection_version": MM_VISUAL_SELECTION_VERSION,
                        "provider_fingerprint": (
                            self.vision.configuration_fingerprint
                        ),
                    },
                    "quality_issue_ids": [
                        issue.issue_id for issue in document.quality_issues
                    ],
                }
                _atomic_json(manifest_path, manifest)
            else:
                document, markdown, token_count, mode = cached
                logger.info(
                    "attachment cache hit document_id=%s mode=%s token_count=%d",
                    document.document_id,
                    mode.value,
                    token_count,
                )
        except Exception as exc:
            _atomic_json(
                manifest_path,
                {
                    "schema_version": "mm-run-0.2",
                    "status": "failed",
                    "source": {"filename": source.name, "sha256": source_sha256},
                    "pipeline_fingerprint": pipeline_fingerprint,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                },
            )
            logger.exception("attachment ingestion failed source=%s", source.name)
            raise

        retrieval = None
        direct_context = None
        if mode is AttachmentMode.DIRECT:
            direct_context = markdown
        else:
            retrieval = await asyncio.to_thread(self._build_retrieval, run_root)
        logger.info(
            "attachment ingestion completed document_id=%s mode=%s elapsed_seconds=%.3f",
            document.document_id,
            mode.value,
            time.monotonic() - started,
        )
        return PreparedAttachment(
            source_path=source,
            document=document,
            mode=mode,
            token_count=token_count,
            markdown_path=markdown_path,
            manifest_path=manifest_path,
            direct_context=direct_context,
            retrieval=retrieval,
        )

    def _pipeline_fingerprint(self) -> str:
        """处理 `_pipeline_fingerprint` 相关逻辑。"""
        return _canonical_sha256(
            {
                "schema": "mm-pipeline-0.3",
                "visual_contract": MM_VISUAL_CONTRACT_VERSION,
                "visual_routing": MM_VISUAL_ROUTING_VERSION,
                "visual_selection": MM_VISUAL_SELECTION_VERSION,
                "parser": self.parser.configuration_fingerprint,
                "vision": self.vision.configuration_fingerprint,
                "prompt_sha256": hashlib.sha256(
                    VLM_DESCRIPTION_PROMPT.encode("utf-8")
                ).hexdigest(),
                "tokenizer": self.token_counter.model_name,
                "direct_context_token_limit": (
                    self.config.direct_context_token_limit
                ),
                "chunk_config": self.chunk_config.model_dump(mode="json"),
            }
        )

    def _route(self, token_count: int) -> AttachmentMode:
        """处理 `_route` 相关逻辑。"""
        return (
            AttachmentMode.DIRECT
            if token_count <= self.config.direct_context_token_limit
            else AttachmentMode.RAG
        )

    def _load_cache(
        self,
        manifest_path: Path,
        document_path: Path,
        markdown_path: Path,
        source_sha256: str,
        pipeline_fingerprint: str,
    ) -> tuple[Any, str, int, AttachmentMode] | None:
        """加载 `cache` 相关数据。"""
        if not all(path.is_file() for path in (manifest_path, document_path, markdown_path)):
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                manifest.get("status") != "success"
                or manifest.get("source", {}).get("sha256") != source_sha256
                or manifest.get("pipeline_fingerprint") != pipeline_fingerprint
                or file_sha256(document_path) != manifest.get("document_sha256")
                or file_sha256(markdown_path) != manifest.get("markdown_sha256")
            ):
                return None
            document = load_document(document_path)
            root = document_path.parent
            for asset in document.assets:
                candidate = (root / asset.path).resolve(strict=True)
                candidate.relative_to(root.resolve())
                if file_sha256(candidate) != asset.sha256:
                    return None
            markdown = markdown_path.read_text(encoding="utf-8")
            token_count = int(manifest["token_count"])
            return document, markdown, token_count, AttachmentMode(manifest["mode"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def _build_retrieval(self, run_root: Path) -> RetrievalService:
        """构建 `retrieval` 相关数据。"""
        started = time.monotonic()
        rag_logger.info("attachment index build started run_root=%s", run_root)
        collection_root, _manifest, _stats = build_collection(
            run_root / "docir",
            run_root / "chunks",
            self.chunk_config,
            resume=True,
        )
        collection = load_chunk_collection(collection_root / "manifest.json")
        index = InMemoryAttachmentIndex()
        IndexingService(collection, index, self.embedding).build()
        service = RetrievalService(
            collection,
            index,
            self.embedding,
            reranker=None,
            config=self.retrieval_config,
        )
        rag_logger.info(
            "attachment index build completed chunks=%d elapsed_seconds=%.3f",
            len(collection.chunks),
            time.monotonic() - started,
        )
        return service
