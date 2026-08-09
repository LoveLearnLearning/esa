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
from backend.agent.DocIR.core.enums import TextOrigin

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "mineru_3_4_4_text_page"


@pytest.mark.skipif(not FIXTURE.exists(), reason="external MinerU fixture not present")
def test_real_mineru_fixture_converts():
    bundle = load_bundle(FIXTURE / "raw")
    document = convert_bundle(bundle, FIXTURE / "assets" / "source.pdf", source_page_count=30)
    assert document.schema_version == "0.2"
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


@pytest.mark.skipif(not FIXTURE.exists(), reason="external MinerU fixture not present")
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


def test_cross_page_table_continuation_becomes_an_extra_region(tmp_path: Path):
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
    assert len(tables) == 1
    assert [region.page_id for region in tables[0].regions] == ["page_000000", "page_000001"]
    assert tables[0].html == "<table><tr><td>A</td></tr></table>"
    assert sum(issue.code == "visual_asset_missing" for issue in document.quality_issues) == 1
    assert tables[0].text.layers[0].origin == TextOrigin.NATIVE_OR_OCR_UNVERIFIED


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
