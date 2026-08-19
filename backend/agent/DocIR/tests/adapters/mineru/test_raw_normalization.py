# backend/agent/DocIR/tests/adapters/mineru/test_raw_normalization.py

"""Stage 4 regression tests for lossless cross-format raw bundle loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.agent.DocIR.adapters.mineru import convert_bundle, load_bundle
from backend.agent.DocIR.adapters.mineru.models import RawMiddleBlock
from backend.agent.rag.chunk import ChunkBuilder


DOCIR_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "fixtures/mineru_adapter/outputs"
SOURCE_ROOT = DOCIR_ROOT / "mineru_adapter_samples"
CASES = {
    "PDF": ("pdf_mixed", "pdf_mixed.pdf", "pipeline"),
    "DOCX": ("docx_mixed", "docx_mixed.docx", "office"),
    "PPTX": ("pptx_mixed", "pptx_mixed.pptx", "office"),
    "XLSX": ("xlsx_mixed", "xlsx_mixed.xlsx", "office"),
    "PNG": ("image_document", "image_document.png", "pipeline"),
    "JPG": ("image_scan", "image_scan.jpg", "pipeline"),
}

EXPECTED_ELEMENT_COUNTS = {
    "PDF": 12,
    "DOCX": 18,
    "PPTX": 21,
    "XLSX": 12,
    "PNG": 9,
    "JPG": 11,
}
requires_multiformat_fixture = pytest.mark.skipif(
    not OUTPUT_ROOT.is_dir() or not SOURCE_ROOT.is_dir(),
    reason="external multiformat MinerU regression data is unavailable",
)


def _bundle_root(format_name: str) -> Path:
    """处理 `_bundle_root` 相关逻辑。"""
    case_name = CASES[format_name][0]
    middle_paths = sorted((OUTPUT_ROOT / case_name).rglob("*_middle.json"))
    assert len(middle_paths) == 1
    return middle_paths[0].parent


def _raw_json(root: Path, suffix: str) -> Any:
    """处理 `_raw_json` 相关逻辑。"""
    paths = sorted(root.glob(f"*{suffix}"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text(encoding="utf-8"))


def _values_for_key(value: Any, key: str) -> list[Any]:
    """处理 `_values_for_key` 相关逻辑。"""
    values: list[Any] = []
    if isinstance(value, dict):
        for child_key, child in value.items():
            if child_key == key:
                values.append(child)
            values.extend(_values_for_key(child, key))
    elif isinstance(value, list):
        for child in value:
            values.extend(_values_for_key(child, key))
    return values


@requires_multiformat_fixture
@pytest.mark.parametrize("format_name", CASES)
def test_six_real_formats_load_without_losing_raw_json(format_name: str) -> None:
    """验证 `six_real_formats_load_without_losing_raw_json` 场景。"""
    root = _bundle_root(format_name)
    bundle = load_bundle(root)
    expected_backend = CASES[format_name][2]

    assert bundle.backend == expected_backend
    assert bundle.version_name == "3.4.4"
    assert bundle.middle.provided_payload() == _raw_json(root, "_middle.json")
    assert bundle.middle_raw == _raw_json(root, "_middle.json")
    assert bundle.content_v2 == _raw_json(root, "_content_list_v2.json")
    assert bundle.content_list == _raw_json(root, "_content_list.json")
    assert bundle.model == _raw_json(root, "_model.json")
    assert set(bundle.raw_json_artifacts) == {
        "middle",
        "content_list",
        "content_list_v2",
        "model",
    }
    assert [group.group_index for group in bundle.v2_groups] == list(
        range(len(bundle.content_v2))
    )
    assert all(group.payload is bundle.content_v2[group.group_index] for group in bundle.v2_groups)


@requires_multiformat_fixture
@pytest.mark.parametrize("format_name", ("DOCX", "PPTX", "XLSX"))
def test_office_missing_geometry_remains_missing(format_name: str) -> None:
    """验证 `office_missing_geometry_remains_missing` 场景。"""
    bundle = load_bundle(_bundle_root(format_name))

    assert bundle.middle.pdf_info
    for page in bundle.middle.pdf_info:
        assert page.page_size is None
        assert page.field_was_provided("page_size") is False
        for block in (*page.para_blocks, *page.discarded_blocks):
            assert block.bbox is None
            assert block.field_was_provided("bbox") is False


@requires_multiformat_fixture
@pytest.mark.parametrize("format_name", ("PDF", "PNG", "JPG"))
def test_pipeline_geometry_and_confidence_are_preserved(format_name: str) -> None:
    """验证 `pipeline_geometry_and_confidence_are_preserved` 场景。"""
    root = _bundle_root(format_name)
    raw = _raw_json(root, "_middle.json")
    bundle = load_bundle(root)

    observed_scores = 0
    for raw_page, page in zip(raw["pdf_info"], bundle.middle.pdf_info, strict=True):
        assert page.page_size == raw_page["page_size"]
        assert page.field_was_provided("page_size") is True
        for raw_block, block in zip(raw_page["para_blocks"], page.para_blocks, strict=True):
            assert block.bbox == raw_block["bbox"]
            assert block.field_was_provided("bbox") is True
            if "score" in raw_block:
                observed_scores += 1
                assert block.score == raw_block["score"]
                assert block.field_was_provided("score") is True
            if "bbox_fs" in raw_block:
                assert block.bbox_fs == raw_block["bbox_fs"]
    assert observed_scores > 0


@requires_multiformat_fixture
def test_office_specific_middle_and_v2_fields_remain_accessible() -> None:
    """验证 `office_specific_middle_and_v2_fields_remain_accessible` 场景。"""
    docx = load_bundle(_bundle_root("DOCX"))
    list_block = next(
        block
        for page in docx.middle.pdf_info
        for block in page.para_blocks
        if block.type == "list"
    )
    assert list_block.attribute == "unordered"
    assert list_block.ilevel == 0
    assert list_block.field_was_provided("attribute") is True
    assert list_block.field_was_provided("ilevel") is True
    assert _values_for_key(docx.middle.provided_payload(), "style")

    v2_list = next(
        block
        for group in docx.v2_groups
        for block in group.blocks or []
        if block.get("type") == "list"
    )
    list_items = v2_list["content"]["list_items"]
    assert [item["ilevel"] for item in list_items] == [0, 0, 0]
    assert [item["prefix"] for item in list_items] == ["-", "-", "-"]

    table = next(
        block
        for group in docx.v2_groups
        for block in group.blocks or []
        if block.get("type") == "table"
    )
    assert table["content"]["table_type"] == "simple_table"
    assert table["content"]["table_nest_level"] == 1
    assert isinstance(table["content"]["html"], str)


@requires_multiformat_fixture
@pytest.mark.parametrize("format_name", ("PPTX", "XLSX"))
def test_office_chart_preserves_present_but_empty_asset_path(format_name: str) -> None:
    """验证 `office_chart_preserves_present_but_empty_asset_path` 场景。"""
    bundle = load_bundle(_bundle_root(format_name))
    chart = next(
        block
        for group in bundle.v2_groups
        for block in group.blocks or []
        if block.get("type") == "chart"
    )
    image_source = chart["content"]["image_source"]

    assert "path" in image_source
    assert image_source["path"] == ""
    assert image_source["path"] is not None
    assert isinstance(chart["content"]["content"], str)
    assert chart["content"]["content"].strip()


def test_raw_model_distinguishes_missing_null_and_empty_values() -> None:
    """验证 `raw_model_distinguishes_missing_null_and_empty_values` 场景。"""
    missing = RawMiddleBlock(type="chart")
    explicit_null = RawMiddleBlock(type="chart", bbox=None)
    empty = RawMiddleBlock(type="chart", bbox=[])

    assert missing.bbox is None
    assert missing.field_was_provided("bbox") is False
    assert "bbox" not in missing.provided_payload()
    assert explicit_null.bbox is None
    assert explicit_null.field_was_provided("bbox") is True
    assert explicit_null.provided_payload()["bbox"] is None
    assert empty.bbox == []
    assert empty.field_was_provided("bbox") is True
    assert empty.provided_payload()["bbox"] == []


@requires_multiformat_fixture
@pytest.mark.parametrize("format_name", ("PDF", "PNG", "JPG"))
def test_pipeline_pdf_and_image_conversion_regression(format_name: str) -> None:
    """验证 `pipeline_pdf_and_image_conversion_regression` 场景。"""
    case_name, filename, _backend = CASES[format_name]
    bundle = load_bundle(_bundle_root(format_name))
    document = convert_bundle(
        bundle,
        SOURCE_ROOT / filename,
        source_page_count=len(bundle.middle.pdf_info),
        strict=True,
    )

    assert document.parsed_page_count == len(bundle.middle.pdf_info)
    assert document.elements
    assert document.parse_revision.backend == "pipeline"
    assert document.source.filename == filename
    assert all(
        locator.kind == "page" and locator.bbox is not None
        for element in document.elements
        for locator in element.locators
    )


@requires_multiformat_fixture
@pytest.mark.parametrize("format_name", ("DOCX", "PPTX", "XLSX"))
def test_office_conversion_uses_real_group_locators_without_geometry(
    format_name: str,
) -> None:
    """验证 `office_conversion_uses_real_group_locators_without_geometry` 场景。"""
    _case_name, filename, _backend = CASES[format_name]
    bundle = load_bundle(_bundle_root(format_name))

    document = convert_bundle(bundle, SOURCE_ROOT / filename, strict=True)

    assert document.pages == ()
    assert document.source_page_count is None
    assert document.parsed_page_count == 0
    assert document.elements
    assert not any(element.kind == "unknown" for element in document.elements)
    assert all(
        locator.kind == "group"
        and locator.page_id is None
        and locator.bbox is None
        and locator.source_geometry is None
        for element in document.elements
        for locator in element.locators
    )
    assert all(element.provenance for element in document.elements)


@requires_multiformat_fixture
@pytest.mark.parametrize("format_name", CASES)
def test_six_formats_convert_to_retrievable_chunks(format_name: str) -> None:
    """验证 `six_formats_convert_to_retrievable_chunks` 场景。"""
    _case_name, filename, _backend = CASES[format_name]
    bundle = load_bundle(_bundle_root(format_name))
    document = convert_bundle(
        bundle,
        SOURCE_ROOT / filename,
        source_page_count=(
            len(bundle.middle.pdf_info) if format_name in {"PDF", "PNG", "JPG"} else None
        ),
        strict=True,
    )

    assert len(document.elements) == EXPECTED_ELEMENT_COUNTS[format_name]
    assert not any(element.kind == "unknown" for element in document.elements)
    assert all(element.provenance for element in document.elements)
    assert any(element.kind == "heading" for element in document.elements)
    assert any(element.kind == "table" for element in document.elements)

    chunks = ChunkBuilder().build(document, docir_sha256="c" * 64)
    assert chunks.chunks
    assert all(chunk.evidence for chunk in chunks.chunks)
