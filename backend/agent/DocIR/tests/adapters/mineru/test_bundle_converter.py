# backend/agent/DocIR/tests/adapters/mineru/test_bundle_converter.py

"""

这个文件干什么：使用真实 MinerU 样本验证 bundle 加载、DocIR 转换和资源保留。

直白点说就是：拿真实 MinerU 产物走一遍转换，确认表格跨页、图片资源和严格对齐都没有丢。
"""

import hashlib
from pathlib import Path

import pytest

from backend.agent.DocIR.adapters.mineru import convert_bundle, load_bundle
from backend.agent.DocIR.adapters.mineru.bundle import MinerUBundle
from backend.agent.DocIR.adapters.mineru.models import (
    RawMiddleBlock,
    RawMiddleDocument,
    RawMiddlePage,
)
from backend.agent.DocIR.core.enums import ElementRole, TextOrigin
from backend.agent.rag.chunk import ChunkBuilder

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "mineru_3_4_4_text_page"
requires_real_fixture = pytest.mark.skipif(
    not (FIXTURE / "raw").is_dir() or not (FIXTURE / "assets" / "source.pdf").is_file(),
    reason="checkout does not include the external MinerU fixture",
)


@requires_real_fixture
def test_real_mineru_fixture_converts():
    bundle = load_bundle(FIXTURE / "raw")
    document = convert_bundle(bundle, FIXTURE / "assets" / "source.pdf", source_page_count=30)
    assert document.schema_name == "docir"
    assert document.parsed_page_count == 1
    assert document.source_page_count == 30
    assert len(document.elements) == 25
    assert len(document.quality_issues) == 25
    assert all(len(section.element_ids) == len(set(section.element_ids)) for section in document.sections)
    assert all(
        layer.origin == TextOrigin.NATIVE_OR_OCR_UNVERIFIED
        for element in document.elements
        if element.text
        for layer in element.text.layers
    )


@requires_real_fixture
def test_real_mineru_fixture_passes_strict_alignment():
    bundle = load_bundle(FIXTURE / "raw")
    document = convert_bundle(
        bundle,
        FIXTURE / "assets" / "source.pdf",
        source_page_count=30,
        strict=True,
    )
    assert len(document.elements) == 25
    assert not any(element.kind == "unknown" for element in document.elements)
    assert not any(issue.code == "middle_v2_mismatch" for issue in document.quality_issues)


def test_cross_page_table_continuation_does_not_guess_its_owner(tmp_path: Path):
    middle_path = tmp_path / "sample_middle.json"
    v2_path = tmp_path / "sample_content_list_v2.json"
    middle_path.write_text("{}")
    v2_path.write_text("[]")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-placeholder")
    owner = RawMiddleBlock(
        type="table",
        bbox=[100, 100, 900, 900],
        index=0,
        blocks=[{
            "type": "table_body",
            "lines": [{"spans": [{"type": "table", "html": "<table><tr><td>A</td></tr></table>"}]}],
        }],
    )
    continuation = RawMiddleBlock(
        type="table",
        bbox=[100, 50, 900, 900],
        index=0,
        blocks=[{"type": "table_body", "lines": [], "lines_deleted": True}],
    )
    middle = RawMiddleDocument(
        pdf_info=[
            RawMiddlePage(page_idx=0, page_size=[1000, 1000], para_blocks=[owner]),
            RawMiddlePage(page_idx=1, page_size=[1000, 1000], para_blocks=[continuation]),
        ],
        _backend="pipeline",
        _version_name="3.4.4",
    )
    content_v2 = [
        [{
            "type": "table",
            "bbox": [100, 100, 900, 900],
            "content": {
                "html": "<table><tr><td>A</td></tr></table>",
                "image_source": {"path": "images/table.jpg"},
            },
        }],
        [{
            "type": "table",
            "bbox": [100, 50, 900, 900],
            "content": {"html": "", "image_source": {"path": "images/"}},
        }],
    ]
    bundle = MinerUBundle(tmp_path, middle_path, v2_path, None, middle, content_v2)

    document = convert_bundle(bundle, source, source_page_count=2, strict=True)

    tables = [element for element in document.elements if element.kind == "table"]
    assert len(tables) == 2
    assert [locator.page_id for locator in tables[0].locators] == ["page_000000"]
    assert [locator.page_id for locator in tables[1].locators] == ["page_000001"]
    assert tables[0].html == "<table><tr><td>A</td></tr></table>"
    assert tables[1].html == ""
    assert any(
        issue.code == "table_continuation_target_unavailable"
        and issue.object_id == tables[1].element_id
        for issue in document.quality_issues
    )
    assert sum(issue.code == "visual_asset_missing" for issue in document.quality_issues) == 1
    assert tables[0].text.layers[0].origin == TextOrigin.NATIVE_OR_OCR_UNVERIFIED


def test_explicit_mineru_heading_levels_form_a_nested_section_tree(tmp_path: Path):
    middle_path = tmp_path / "sample_middle.json"
    v2_path = tmp_path / "sample_content_list_v2.json"
    middle_path.write_text("{}")
    v2_path.write_text("[]")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-placeholder")
    outline = (
        ("第一章", 1),
        ("1.1", 2),
        ("1.1.1", 3),
        ("1.2", 2),
        ("第二章", 1),
    )
    blocks = []
    v2_items = []
    for index, (text, level) in enumerate(outline):
        bbox = [10, index * 100 + 10, 900, index * 100 + 60]
        blocks.append(
            RawMiddleBlock(
                type="title",
                bbox=bbox,
                index=index,
                level=level,
                lines=[{"spans": [{"type": "text", "content": text}]}],
            )
        )
        v2_items.append(
            {
                "type": "title",
                "bbox": bbox,
                "content": {
                    "title_content": [{"type": "text", "content": text}],
                    "level": level,
                },
            }
        )
    middle = RawMiddleDocument(
        pdf_info=[
            RawMiddlePage(
                page_idx=0,
                page_size=[1000, 1000],
                para_blocks=blocks,
            )
        ],
        _backend="pipeline",
        _version_name="3.4.4",
    )
    bundle = MinerUBundle(tmp_path, middle_path, v2_path, None, middle, [v2_items])

    document = convert_bundle(bundle, source, source_page_count=1, strict=True)

    headings = {
        element.text.layers[0].text: element
        for element in document.elements
        if element.kind == "heading"
    }
    sections = {
        section.title_element_id: section
        for section in document.sections
        if section.title_element_id is not None
    }
    assert sections[headings["第一章"].element_id].parent_section_id == "section_root"
    assert (
        sections[headings["1.1"].element_id].parent_section_id
        == headings["第一章"].section_id
    )
    assert (
        sections[headings["1.1.1"].element_id].parent_section_id
        == headings["1.1"].section_id
    )
    assert (
        sections[headings["1.2"].element_id].parent_section_id
        == headings["第一章"].section_id
    )
    assert sections[headings["第二章"].element_id].parent_section_id == "section_root"


def test_missing_heading_level_stays_unknown_and_creates_no_relation(tmp_path: Path):
    middle_path = tmp_path / "sample_middle.json"
    v2_path = tmp_path / "sample_content_list_v2.json"
    middle_path.write_text("{}")
    v2_path.write_text("[]")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-placeholder")
    block = RawMiddleBlock(
        type="title",
        bbox=[10, 10, 900, 60],
        index=0,
        lines=[{"spans": [{"type": "text", "content": "级别未知标题"}]}],
    )
    middle = RawMiddleDocument(
        pdf_info=[
            RawMiddlePage(
                page_idx=0,
                page_size=[1000, 1000],
                para_blocks=[block],
            )
        ],
        _backend="pipeline",
        _version_name="3.4.4",
    )
    content_v2 = [[{
        "type": "title",
        "bbox": [10, 10, 900, 60],
        "content": {
            "title_content": [{"type": "text", "content": "级别未知标题"}]
        },
    }]]
    bundle = MinerUBundle(tmp_path, middle_path, v2_path, None, middle, content_v2)

    document = convert_bundle(bundle, source, source_page_count=1, strict=True)

    heading = document.elements[0]
    assert heading.kind == "heading"
    assert heading.level is None
    assert heading.section_id == "section_root"
    assert len(document.sections) == 1
    assert document.sections[0].title_element_id is None
    assert heading.parent_element_id is None
    assert heading.caption_element_ids == ()
    assert heading.footnote_element_ids == ()
    assert any(issue.code == "heading_level_missing" for issue in document.quality_issues)

    chunks = ChunkBuilder().build(document, docir_sha256="c" * 64)
    assert any("级别未知标题" in chunk.bm25_body for chunk in chunks.chunks)


def test_existing_visual_file_becomes_a_hashed_docir_asset(tmp_path: Path):
    middle_path = tmp_path / "sample_middle.json"
    v2_path = tmp_path / "sample_content_list_v2.json"
    middle_path.write_text("{}")
    v2_path.write_text("[]")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-placeholder")
    image = tmp_path / "images" / "table.jpg"
    image.parent.mkdir()
    image.write_bytes(b"jpeg-placeholder")
    block = RawMiddleBlock(
        type="table",
        bbox=[100, 100, 900, 900],
        index=0,
        blocks=[{"type": "table_body", "lines": []}],
    )
    middle = RawMiddleDocument(
        pdf_info=[RawMiddlePage(page_idx=0, page_size=[1000, 1000], para_blocks=[block])],
        _backend="pipeline",
        _version_name="3.4.4",
    )
    content_v2 = [[{
        "type": "table",
        "bbox": [100, 100, 900, 900],
        "content": {"html": "<table></table>", "image_source": {"path": "images/table.jpg"}},
    }]]
    bundle = MinerUBundle(tmp_path, middle_path, v2_path, None, middle, content_v2)

    document = convert_bundle(bundle, source, source_page_count=1, strict=True)

    table = next(element for element in document.elements if element.kind == "table")
    asset = next(asset for asset in document.assets if asset.asset_id == table.asset_id)
    assert asset.kind.value == "table"
    assert asset.path.startswith("assets/visual/")
    assert asset.sha256 == hashlib.sha256(image.read_bytes()).hexdigest()
    assert not any(issue.code.startswith("visual_asset_") for issue in document.quality_issues)


def test_page_footer_becomes_a_footer_paragraph(tmp_path: Path):
    middle_path = tmp_path / "sample_middle.json"
    v2_path = tmp_path / "sample_content_list_v2.json"
    middle_path.write_text("{}")
    v2_path.write_text("[]")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-placeholder")
    block = RawMiddleBlock(
        type="page_footer",
        bbox=[10, 900, 990, 990],
        index=0,
        blocks=[],
    )
    middle = RawMiddleDocument(
        pdf_info=[
            RawMiddlePage(
                page_idx=0,
                page_size=[1000, 1000],
                para_blocks=[],
                discarded_blocks=[block],
            )
        ],
        _backend="pipeline",
        _version_name="3.4.4",
    )
    content_v2 = [[{
        "type": "page_footer",
        "bbox": [10, 900, 990, 990],
        "content": {
            "page_footer_content": [{"type": "text", "content": "出版社"}]
        },
    }]]
    bundle = MinerUBundle(tmp_path, middle_path, v2_path, None, middle, content_v2)

    document = convert_bundle(bundle, source, source_page_count=1, strict=True)

    footer = document.elements[0]
    assert footer.kind == "paragraph"
    assert footer.role == ElementRole.FOOTER
    assert footer.text.layers[0].text == "出版社"
    assert not any(issue.code == "unknown_element_type" for issue in document.quality_issues)
