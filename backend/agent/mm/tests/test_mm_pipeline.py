# backend/agent/mm/tests/test_mm_pipeline.py

"""验证 `mm_pipeline` 相关行为与回归场景。"""

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
    FormulaElement,
    Locator,
    ParseRevision,
    Section,
    SourceVersion,
    TableElement,
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
    """封装 `FakeParser` 的状态与行为。"""
    configuration_fingerprint = "f" * 64

    def __init__(self) -> None:
        """初始化 `FakeParser` 实例。"""
        self.calls = 0

    def parse(self, source: Path, document_root: Path) -> ParsedAttachment:
        """解析 `parse` 相关数据。

        Args:
            source: Path => `source` 参数。
            document_root: Path => `document_root` 参数。

        Returns:
            ParsedAttachment => 处理结果。
        """
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
            locators=(
                Locator(
                    locator_id="locator_figure_1",
                    kind="page",
                    label="第 1 页",
                ),
            ),
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
    """封装 `FakeVision` 的状态与行为。"""
    provider_name = "fake-vlm"
    model_name = "fake-vision"
    model_revision = "r1"
    configuration_fingerprint = "v" * 64

    def __init__(self, *, fail: bool = False) -> None:
        """初始化 `FakeVision` 实例。"""
        self.calls = 0
        self.fail = fail

    async def analyze(self, image: bytes, media_type: str, prompt: str) -> VisualAnalysis:
        """处理 `analyze` 相关逻辑。

        Args:
            image: bytes => `image` 参数。
            media_type: str => `media_type` 参数。
            prompt: str => `prompt` 参数。

        Returns:
            VisualAnalysis => 处理结果。
        """
        self.calls += 1
        if self.fail:
            raise RuntimeError("unavailable")
        return VisualAnalysis(
            description="客户端、路由器和服务器组成的网络拓扑图",
            visible_text="Client Router Server",
            content_type="figure",
        )


class FixedTokenCounter:
    """封装 `FixedTokenCounter` 的状态与行为。"""
    model_name = "fake-qwen-tokenizer"

    def __init__(self, count: int) -> None:
        """初始化 `FixedTokenCounter` 实例。"""
        self.count = count

    def count_tokens(self, text: str) -> int:
        """统计 `tokens` 相关数据。"""
        return self.count


def make_config(tmp_path: Path, limit: int = 48_000) -> MMConfig:
    """处理 `make_config` 相关逻辑。

    Args:
        tmp_path: Path => `tmp_path` 参数。
        limit: int => 返回数量上限。

    Returns:
        MMConfig => 处理结果。
    """
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
    """验证 `visual_enrichment_is_attached_after_parent` 场景。"""
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
    assert derived.locators[0].locator_id != "locator_figure_1"
    assert derived.locators[0].label == "第 1 页"
    assert derived.text.layers[0].origin is TextOrigin.VLM_DERIVED
    assert derived.text.layers[0].quote_eligible is False
    assert result.outcomes[0].decision.value == "accept"
    assert result.outcomes[0].write_to_docir is True
    assert result.document.sections[0].element_ids[-1] == derived.element_id
    assert "网络拓扑图" in render_document_markdown(result.document)


def test_vlm_failure_records_warning_and_keeps_document_valid(tmp_path: Path) -> None:
    """验证 `vlm_failure_records_warning_and_keeps_document_valid` 场景。"""
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


def test_missing_visual_asset_is_marked_for_review(tmp_path: Path) -> None:
    """缺少可解析资产时不得静默跳过视觉元素。"""
    source = tmp_path / "note.png"
    source.write_bytes(b"image")
    parsed = FakeParser().parse(source, tmp_path / "doc")
    figure = parsed.document.elements[0].model_copy(update={"asset_id": None})
    document = Document.model_validate(
        {
            **parsed.document.model_dump(mode="python"),
            "elements": (figure,),
        }
    )

    result = asyncio.run(enrich_visual_assets(document, parsed.document_root, FakeVision()))

    assert result.reviewed_assets == ("figure_1",)
    assert result.document.quality_issues[0].code == "visual_enrichment_review_required"
    assert result.document.elements[0].quality_issue_ids
    assert len(result.document.elements) == 1


def test_same_visual_bytes_are_analyzed_once(tmp_path: Path) -> None:
    """验证 `same_visual_bytes_are_analyzed_once` 场景。"""
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
            "locators": (
                parsed.document.elements[0].locators[0].model_copy(
                    update={"locator_id": "locator_figure_2"}
                ),
            ),
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


def test_structured_tables_formulas_and_charts_skip_vlm(tmp_path: Path) -> None:
    """验证 `structured_tables_formulas_and_charts_skip_vlm` 场景。"""
    source = tmp_path / "note.png"
    source.write_bytes(b"image")
    parsed = FakeParser().parse(source, tmp_path / "doc")
    assets = list(parsed.document.assets)
    elements = list(parsed.document.elements)
    section_ids = ["figure_1"]
    for asset_id, kind, filename, element in (
        (
            "table",
            AssetKind.TABLE,
            "table.png",
            TableElement(
                element_id="table_1",
                document_order=1,
                section_id="root",
                source_type="table",
                html="<table><tr><td>already parsed</td></tr></table>",
                asset_id="table",
                locators=(Locator(locator_id="locator_table_1", kind="page"),),
            ),
        ),
        (
            "formula",
            AssetKind.FIGURE,
            "formula.png",
            FormulaElement(
                element_id="formula_1",
                document_order=2,
                section_id="root",
                source_type="equation_interline",
                latex="x = 1",
                asset_id="formula",
                locators=(Locator(locator_id="locator_formula_1", kind="page"),),
            ),
        ),
        (
            "chart",
            AssetKind.FIGURE,
            "chart.png",
            FigureElement(
                element_id="chart_1",
                document_order=3,
                section_id="root",
                source_type="chart",
                structured_content="x-axis: time; y-axis: score",
                asset_id="chart",
                locators=(Locator(locator_id="locator_chart_1", kind="page"),),
            ),
        ),
    ):
        payload = asset_id.encode()
        digest = hashlib.sha256(payload).hexdigest()
        (parsed.document_root / "assets" / filename).write_bytes(payload)
        assets.append(
            Asset(
                asset_id=asset_id,
                kind=kind,
                path=f"assets/{filename}",
                media_type="image/png",
                byte_size=len(payload),
                sha256=digest,
            )
        )
        elements.append(element)
        section_ids.append(element.element_id)
    document = Document.model_validate(
        {
            **parsed.document.model_dump(mode="python"),
            "assets": tuple(assets),
            "elements": tuple(elements),
            "sections": (
                parsed.document.sections[0].model_copy(
                    update={"element_ids": tuple(section_ids)}
                ),
            ),
        }
    )
    vision = FakeVision()
    result = asyncio.run(
        enrich_visual_assets(document, parsed.document_root, vision)
    )

    assert vision.calls == 1
    assert result.analyzed_assets == 1
    assert len(result.document.elements) == 5


def test_direct_route_and_persistent_cache(tmp_path: Path) -> None:
    """验证 `direct_route_and_persistent_cache` 场景。"""
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
    """验证 `large_document_builds_ephemeral_rag_over_vlm_text` 场景。"""
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
