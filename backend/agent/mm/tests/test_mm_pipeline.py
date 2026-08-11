from __future__ import annotations

import hashlib
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from backend.agent.DocIR import (
    Asset,
    AssetKind,
    Document,
    FigureElement,
    ParseRevision,
    Section,
    SourceVersion,
    TextOrigin,
    ValidationStatus,
    ValidationSummary,
)
from backend.agent.mm import (
    AttachmentMode,
    MMConfig,
    MultimodalIngestionService,
    ParsedAttachment,
    VisualAnalysis,
    enrich_visual_assets,
    render_document_markdown,
)
from backend.agent.rag.inference import HashingEmbeddingProvider


class FakeParser:
    configuration_fingerprint = "f" * 64

    def __init__(self) -> None:
        self.calls = 0

    def parse(self, source: Path, document_root: Path) -> ParsedAttachment:
        self.calls += 1
        payload = source.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        assets = document_root / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        (assets / source.name).write_bytes(payload)
        (assets / "visual.png").write_bytes(payload)
        original = Asset(
            asset_id="original",
            kind=AssetKind.ORIGINAL,
            path=f"assets/{source.name}",
            media_type="image/png",
            byte_size=len(payload),
            sha256=digest,
        )
        visual = Asset(
            asset_id="visual",
            kind=AssetKind.FIGURE,
            path="assets/visual.png",
            media_type="image/png",
            byte_size=len(payload),
            sha256=digest,
        )
        figure = FigureElement(
            element_id="figure_1",
            document_order=0,
            section_id="root",
            asset_id="visual",
            source_type="image",
        )
        document = Document(
            document_id="document_1",
            created_at=datetime.now(timezone.utc),
            source=SourceVersion(
                source_version_id="source_1",
                filename=source.name,
                media_type="image/png",
                byte_size=len(payload),
                sha256=digest,
                original_asset_id="original",
            ),
            parse_revision=ParseRevision(
                parse_revision_id="parse_1",
                parser_name="fake",
                parser_version="1",
                config_sha256="a" * 64,
            ),
            sections=(Section(section_id="root", element_ids=("figure_1",)),),
            elements=(figure,),
            assets=(original, visual),
            validation=ValidationSummary(status=ValidationStatus.PASSED),
        )
        return ParsedAttachment(document, document_root)


class FakeVision:
    provider_name = "fake-vlm"
    model_name = "fake-vision"
    model_revision = "r1"
    configuration_fingerprint = "v" * 64

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def analyze(self, image: bytes, media_type: str, prompt: str) -> VisualAnalysis:
        self.calls += 1
        if self.fail:
            raise RuntimeError("unavailable")
        return VisualAnalysis(
            description="客户端、路由器和服务器组成的网络拓扑图",
            visible_text="Client Router Server",
            content_type="figure",
        )


class FixedTokenCounter:
    model_name = "fake-qwen-tokenizer"

    def __init__(self, count: int) -> None:
        self.count = count

    def count_tokens(self, text: str) -> int:
        return self.count


def make_config(tmp_path: Path, limit: int = 48_000) -> MMConfig:
    return MMConfig(
        artifact_root=tmp_path / "runtime",
        direct_context_token_limit=limit,
        tokenizer_path="unused",
        mineru_command=tmp_path / "mineru",
        mineru_timeout_seconds=10,
        mineru_attempts=1,
        vlm_base_url="http://vlm.invalid/v1",
        vlm_model="fake-vision",
        vlm_model_revision="r1",
        vlm_timeout_seconds=10,
        vlm_attempts=1,
        vlm_max_concurrency=2,
        embedding_model="unused",
        embedding_device="cpu",
    )


def test_visual_enrichment_is_attached_after_parent(tmp_path: Path) -> None:
    source = tmp_path / "note.png"
    source.write_bytes(b"not-a-real-png")
    parsed = FakeParser().parse(source, tmp_path / "doc")
    result = asyncio.run(
        enrich_visual_assets(parsed.document, parsed.document_root, FakeVision())
    )

    assert [item.element_id for item in result.document.elements] == [
        "figure_1",
        result.document.elements[1].element_id,
    ]
    derived = result.document.elements[1]
    assert derived.parent_element_id == "figure_1"
    assert derived.text.layers[0].origin is TextOrigin.VLM_DERIVED
    assert derived.text.layers[0].quote_eligible is False
    assert result.document.sections[0].element_ids[-1] == derived.element_id
    assert "网络拓扑图" in render_document_markdown(result.document)


def test_vlm_failure_records_warning_and_keeps_document_valid(tmp_path: Path) -> None:
    source = tmp_path / "note.png"
    source.write_bytes(b"image")
    parsed = FakeParser().parse(source, tmp_path / "doc")
    result = asyncio.run(
        enrich_visual_assets(
            parsed.document, parsed.document_root, FakeVision(fail=True)
        )
    )

    assert len(result.document.elements) == 1
    assert result.failed_assets == ("visual",)
    assert result.document.quality_issues[0].code == "vlm_description_failed"
    assert result.document.validation.status is ValidationStatus.PASSED_WITH_WARNINGS


def test_same_visual_bytes_are_analyzed_once(tmp_path: Path) -> None:
    source = tmp_path / "note.png"
    source.write_bytes(b"same-image")
    parsed = FakeParser().parse(source, tmp_path / "doc")
    second_asset = parsed.document.assets[1].model_copy(
        update={"asset_id": "visual_2"}
    )
    second_figure = parsed.document.elements[0].model_copy(
        update={
            "element_id": "figure_2",
            "document_order": 1,
            "asset_id": "visual_2",
        }
    )
    document = Document.model_validate(
        {
            **parsed.document.model_dump(mode="python"),
            "assets": (*parsed.document.assets, second_asset),
            "elements": (*parsed.document.elements, second_figure),
            "sections": (
                parsed.document.sections[0].model_copy(
                    update={"element_ids": ("figure_1", "figure_2")}
                ),
            ),
        }
    )
    vision = FakeVision()
    result = asyncio.run(enrich_visual_assets(document, parsed.document_root, vision))

    assert vision.calls == 1
    assert result.analyzed_assets == 1
    assert len(result.document.elements) == 4


def test_direct_route_and_persistent_cache(tmp_path: Path) -> None:
    source = tmp_path / "note.png"
    source.write_bytes(b"image")
    parser = FakeParser()
    vision = FakeVision()
    service = MultimodalIngestionService(
        make_config(tmp_path),
        parser=parser,
        vision=vision,
        token_counter=FixedTokenCounter(48_000),
        embedding=HashingEmbeddingProvider(),
    )

    first = asyncio.run(service.prepare_file(source))
    second = asyncio.run(service.prepare_file(source))

    assert first.mode is AttachmentMode.DIRECT
    assert first.direct_context and "网络拓扑图" in first.direct_context
    assert first.retrieval is None
    assert parser.calls == 1
    assert vision.calls == 1
    assert second.manifest_path == first.manifest_path


def test_large_document_builds_ephemeral_rag_over_vlm_text(tmp_path: Path) -> None:
    source = tmp_path / "note.png"
    source.write_bytes(b"image")
    service = MultimodalIngestionService(
        make_config(tmp_path),
        parser=FakeParser(),
        vision=FakeVision(),
        token_counter=FixedTokenCounter(48_001),
        embedding=HashingEmbeddingProvider(),
    )

    prepared = asyncio.run(service.prepare_file(source))
    response = prepared.context_for("网络拓扑图中的路由器")

    assert prepared.mode is AttachmentMode.RAG
    assert prepared.direct_context is None
    assert response.hits
    assert any(
        evidence.text_origin == TextOrigin.VLM_DERIVED.value
        for hit in response.hits
        for evidence in hit.evidence
    )
    assert any(
        "visual" in evidence.asset_ids
        for hit in response.hits
        for evidence in hit.evidence
        if evidence.text_origin == TextOrigin.VLM_DERIVED.value
    )
