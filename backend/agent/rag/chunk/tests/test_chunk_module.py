# backend/agent/rag/chunk/tests/test_chunk_module.py

"""

这个文件干什么：验证从 DocIR 构建 Chunk 的切分、重叠、表格、证据和序列化规则。

直白点说就是：用各种文档样本检查切块不会丢字、越界或丢证据，保存后也必须能原样读回。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.agent.DocIR.core import (
    Asset,
    AssetKind,
    Document,
    ElementRole,
    FigureElement,
    HeadingElement,
    NormalizedBox,
    Page,
    PageRange,
    ParagraphElement,
    ParseRevision,
    Region,
    Section,
    SourceVersion,
    TableElement,
    TextContent,
    TextLayer,
    TextOrigin,
    ValidationStatus,
    ValidationSummary,
)
from backend.agent.DocIR.io import save_document
from backend.agent.rag.chunk import (
    ChunkBuilder,
    ChunkConfig,
    load_chunk_document,
    save_json,
    split_text_spans,
)
from backend.agent.rag.chunk.cli import build_collection
from backend.agent.rag.chunk.serializer import file_sha256


def _text(element_id: str, value: str) -> TextContent | None:
    if not value:
        return None
    layer_id = f"text_{element_id}"
    return TextContent(
        primary_layer_id=layer_id,
        layers=(
            TextLayer(
                text_layer_id=layer_id,
                origin=TextOrigin.NATIVE_OR_OCR_UNVERIFIED,
                text=value,
                quote_eligible=False,
            ),
        ),
    )


def make_document(specs: list[dict]) -> Document:
    elements = []
    all_region_ids = []
    for index, spec in enumerate(specs):
        element_id = f"element_{index}"
        regions = [
            Region(
                region_id=f"region_{index}_0",
                page_id="page_000000",
                bbox=NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2),
            )
        ]
        if spec.get("multipage"):
            regions.append(
                Region(
                    region_id=f"region_{index}_1",
                    page_id="page_000001",
                    bbox=NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2),
                )
            )
        all_region_ids.extend(region.region_id for region in regions)
        common = {
            "element_id": element_id,
            "document_order": index,
            "role": spec.get("role", ElementRole.BODY),
            "section_id": "section_root",
            "regions": tuple(regions),
            "text": _text(element_id, spec.get("text", "")),
            "source_type": spec.get("kind", "paragraph"),
        }
        kind = spec.get("kind", "paragraph")
        if kind == "heading":
            element = HeadingElement(**common, level=1)
        elif kind == "table":
            element = TableElement(**common, html=spec.get("html"), asset_id=None)
        elif kind == "figure":
            element = FigureElement(**common, asset_id=None)
        else:
            element = ParagraphElement(**common)
        elements.append(element)
    heading = next((item.element_id for item in elements if item.kind == "heading"), None)
    return Document(
        document_id="doc_test",
        created_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        source=SourceVersion(
            source_version_id="src_test",
            filename="测试文档.pdf",
            media_type="application/pdf",
            byte_size=10,
            sha256="b" * 64,
            original_asset_id="asset_original",
        ),
        parse_revision=ParseRevision(
            parse_revision_id="parse_test",
            parser_name="test",
            parser_version="1",
            page_range=PageRange(start=0, end=1),
            config={},
            config_sha256="a" * 64,
        ),
        source_page_count=2,
        parsed_page_count=2,
        pages=(
            Page(page_id="page_000000", page_index=0, display_page_no=1, width=100, height=100),
            Page(page_id="page_000001", page_index=1, display_page_no=2, width=100, height=100),
        ),
        sections=(
            Section(
                section_id="section_root",
                title_element_id=heading,
                element_ids=tuple(item.element_id for item in elements),
            ),
        ),
        elements=tuple(elements),
        assets=(
            Asset(
                asset_id="asset_original",
                kind=AssetKind.ORIGINAL,
                path="assets/source.pdf",
                media_type="application/pdf",
                byte_size=10,
                sha256="b" * 64,
            ),
        ),
        validation=ValidationSummary(status=ValidationStatus.PASSED),
    )


def test_config_is_strict_and_ordered() -> None:
    assert ChunkConfig().sha256 == ChunkConfig().sha256
    with pytest.raises(ValidationError, match="target_chars"):
        ChunkConfig(target_chars=20, max_chars=10)
    with pytest.raises(ValidationError):
        ChunkConfig.model_validate({"extra": 1})


def test_text_split_prefers_boundaries_and_preserves_offsets() -> None:
    text = "第一句。第二句很长。第三句。"
    pieces = split_text_spans(text, 8)
    assert all(len(value) <= 8 for value, _start, _end in pieces)
    assert all(text[start:end] == value for value, start, end in pieces)
    assert "".join(value for value, _start, _end in pieces) == text


def test_heading_roles_and_empty_figure_have_explicit_dispositions() -> None:
    document = make_document([
        {"kind": "heading", "text": "第一章"},
        {"text": "正文内容"},
        {"text": "页眉", "role": ElementRole.HEADER},
        {"kind": "figure", "text": ""},
    ])
    result = ChunkBuilder().build(document, docir_sha256="c" * 64)
    disposition = {item.element_id: (item.action, item.reason) for item in result.element_dispositions}
    assert disposition["element_0"] == ("section_structure", "heading_in_section_path")
    assert disposition["element_2"] == ("excluded", "excluded_role:header")
    assert disposition["element_3"] == ("excluded", "empty_figure_no_vlm")
    assert result.chunks[0].section_path == ("第一章",)
    assert "页眉" not in result.chunks[0].bm25_body


def test_normal_chunks_overlap_one_whole_element_and_mark_group() -> None:
    document = make_document([
        {"text": "甲" * 10},
        {"text": "乙" * 10},
        {"text": "丙" * 10},
    ])
    result = ChunkBuilder(ChunkConfig(target_chars=15, max_chars=30)).build(document, docir_sha256="c" * 64)
    assert len(result.chunks) == 3
    assert result.chunks[0].evidence[0].evidence_id == result.chunks[1].evidence[0].evidence_id
    assert result.chunks[1].evidence[-1].evidence_id == result.chunks[2].evidence[0].evidence_id
    assert all(chunk.overlap_group_ids for chunk in result.chunks)
    assert all(chunk.body_char_count <= 30 for chunk in result.chunks)


def test_overlap_is_skipped_when_it_would_exceed_hard_limit() -> None:
    document = make_document([{"text": "甲" * 25}, {"text": "乙" * 10}])
    result = ChunkBuilder(ChunkConfig(target_chars=20, max_chars=30)).build(document, docir_sha256="c" * 64)
    assert len(result.chunks) == 2
    assert not result.chunks[0].overlap_group_ids
    assert not result.chunks[1].overlap_group_ids


def test_oversized_element_splits_without_losing_text() -> None:
    value = "长句。" * 30
    document = make_document([{"text": value}])
    result = ChunkBuilder(ChunkConfig(target_chars=20, max_chars=25)).build(document, docir_sha256="c" * 64)
    evidence = [item.text for chunk in result.chunks for item in chunk.evidence]
    assert "".join(evidence) == value
    assert all(chunk.body_char_count <= 25 for chunk in result.chunks)


def test_table_uses_repeated_header_and_consecutive_row_groups() -> None:
    html = "<table><thead><tr><th>姓名</th><th>分数</th></tr></thead><tbody>" + "".join(
        f"<tr><td>学生{i}</td><td>{i}</td></tr>" for i in range(8)
    ) + "</tbody></table>"
    document = make_document([{"kind": "table", "text": "表格文字", "html": html, "multipage": True}])
    result = ChunkBuilder(ChunkConfig(target_chars=30, max_chars=45)).build(document, docir_sha256="c" * 64)
    assert len(result.chunks) > 1
    assert all(chunk.bm25_body.startswith("姓名 | 分数") for chunk in result.chunks)
    assert all(chunk.body_char_count <= 45 for chunk in result.chunks)
    assert all(len(chunk.evidence[0].page_ids) == 2 for chunk in result.chunks)
    combined = "\n".join(chunk.bm25_body for chunk in result.chunks)
    assert all(combined.count(f"学生{i} | {i}") == 1 for i in range(8))


def test_table_without_html_falls_back_to_primary_text() -> None:
    document = make_document([{"kind": "table", "text": "A B C " * 20, "html": None}])
    result = ChunkBuilder(ChunkConfig(target_chars=20, max_chars=25)).build(document, docir_sha256="c" * 64)
    assert result.chunks
    assert all(item.derivation == "table_text_fallback" for chunk in result.chunks for item in chunk.evidence)
    assert all(chunk.body_char_count <= 25 for chunk in result.chunks)


def test_unverified_text_is_retrievable_but_not_quotable() -> None:
    result = ChunkBuilder().build(make_document([{"text": "OCR 风险内容"}]), docir_sha256="c" * 64)
    evidence = result.chunks[0].evidence[0]
    assert evidence.text_origin == TextOrigin.NATIVE_OR_OCR_UNVERIFIED
    assert evidence.quote_eligible is False
    assert "chunk_ocr_risk_unverified_origin" in evidence.quality_issue_ids


def test_serialization_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    document = ChunkBuilder().build(make_document([{"text": "稳定输出"}]), docir_sha256="c" * 64)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    save_json(document, first)
    save_json(document, second)
    assert first.read_bytes() == second.read_bytes()
    assert load_chunk_document(first) == document


def test_build_collection_resume_verifies_existing_document(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    bundle = input_root / "one"
    bundle.mkdir(parents=True)
    save_document(make_document([{"text": "真实语料"}]), bundle / "document.json")
    output_root = tmp_path / "output"
    root, first, _stats = build_collection(input_root, output_root, ChunkConfig(), resume=True)
    document_path = root / first.documents[0].path
    before = file_sha256(document_path)
    root2, second, _stats2 = build_collection(input_root, output_root, ChunkConfig(), resume=True)
    assert root2 == root and second == first and file_sha256(document_path) == before
    changed = load_chunk_document(document_path).model_copy(update={"filename": "被篡改.pdf"})
    save_json(changed, document_path)
    with pytest.raises(ValueError, match="SHA-256"):
        build_collection(input_root, output_root, ChunkConfig(), resume=True)
