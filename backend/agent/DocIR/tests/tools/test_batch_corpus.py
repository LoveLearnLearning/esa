# backend/agent/DocIR/tests/tools/test_batch_corpus.py

"""

这个文件干什么：验证多格式批处理流水线的发现、保留、恢复、校验和汇总规则。

直白点说就是：模拟批量处理支持格式的各种情况，确认入口、断点续跑、文件保留、图片复制和统计报告都按规则工作。
"""

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.agent.DocIR.tools.batch_corpus import (
    aggregate,
    discover_documents,
    find_parse_dir,
    materialize_visual_assets,
    process_document,
    prune_mineru_output,
    should_retain,
    source_metadata,
    stable_directory_name,
)
from backend.agent.DocIR.io import load_document

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mineru_3_4_4_text_page"
DOCIR_ROOT = Path(__file__).resolve().parents[2]
MULTIFORMAT_SOURCES = DOCIR_ROOT / "mineru_adapter_samples"
MULTIFORMAT_OUTPUTS = (
    Path(__file__).resolve().parents[1] / "fixtures/mineru_adapter/outputs"
)
requires_real_fixture = pytest.mark.skipif(
    not (FIXTURE / "raw").is_dir() or not (FIXTURE / "assets" / "source.pdf").is_file(),
    reason="checkout does not include the external MinerU fixture",
)
requires_multiformat_fixture = pytest.mark.skipif(
    not MULTIFORMAT_SOURCES.is_dir() or not MULTIFORMAT_OUTPUTS.is_dir(),
    reason="external multiformat MinerU regression data is unavailable",
)


def test_discover_documents_is_sorted_case_insensitive_and_format_bounded(
    tmp_path: Path,
):
    """验证 `discover_documents_is_sorted_case_insensitive_and_format_bounded` 场景。"""
    (tmp_path / "b.PDF").write_bytes(b"b")
    (tmp_path / "a.pdf").write_bytes(b"a")
    (tmp_path / "c.DOCX").write_bytes(b"c")
    (tmp_path / "d.pptx").write_bytes(b"d")
    (tmp_path / "e.XLSX").write_bytes(b"e")
    (tmp_path / "f.PNG").write_bytes(b"f")
    (tmp_path / "g.jpg").write_bytes(b"g")
    (tmp_path / "note.txt").write_text("x")
    assert [path.name for path in discover_documents(tmp_path)] == [
        "a.pdf",
        "b.PDF",
        "c.DOCX",
        "d.pptx",
        "e.XLSX",
        "f.PNG",
        "g.jpg",
    ]


def test_source_metadata_only_uses_pdf_reader_for_pdf(tmp_path: Path):
    """验证 `source_metadata_only_uses_pdf_reader_for_pdf` 场景。"""
    office = tmp_path / "source.docx"
    office.write_bytes(b"not parsed as a PDF")
    image = tmp_path / "source.png"
    image.write_bytes(b"single input canvas")

    assert source_metadata(office).page_count is None
    assert source_metadata(office).encrypted is None
    assert source_metadata(office).media_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert source_metadata(image).page_count == 1
    assert source_metadata(image).encrypted is None
    assert source_metadata(image).media_type == "image/png"


@requires_multiformat_fixture
def test_pdf_source_metadata_preserves_page_count_and_encryption_behavior():
    """验证 `pdf_source_metadata_preserves_page_count_and_encryption_behavior` 场景。"""
    pytest.importorskip("pypdf")
    metadata = source_metadata(MULTIFORMAT_SOURCES / "pdf_text.pdf")
    assert metadata.page_count == 2
    assert metadata.encrypted is False
    assert metadata.media_type == "application/pdf"


def test_stable_directory_name_uses_hash_and_safe_stem(tmp_path: Path):
    """验证 `stable_directory_name_uses_hash_and_safe_stem` 场景。"""
    path = tmp_path / "报告.pdf"
    path.write_bytes(b"content")
    digest = hashlib.sha256(b"content").hexdigest()
    assert stable_directory_name(path) == f"{digest[:12]}--报告"


def test_retention_policy_is_exact():
    """验证 `retention_policy_is_exact` 场景。"""
    assert should_retain(Path("x_middle.json"))
    assert should_retain(Path("x_content_list_v2.json"))
    assert should_retain(Path("x_model.json"))
    assert should_retain(Path("x.md"))
    assert should_retain(Path("images/table.JPG"))
    assert should_retain(Path("images/figure.png"))
    assert should_retain(Path("x_content_list.json"))
    assert should_retain(Path("x_origin.docx"))
    assert should_retain(Path("unknown-office-artifact.json"))
    assert not should_retain(Path("x_layout.pdf"))
    assert not should_retain(Path("x_span.pdf"))


def test_prune_removes_debug_and_keeps_structural_files(tmp_path: Path):
    """验证 `prune_removes_debug_and_keeps_structural_files` 场景。"""
    nested = tmp_path / "doc" / "auto"
    nested.mkdir(parents=True)
    retained = {
        "figure.jpg",
        "unknown.json",
        "x.md",
        "x_content_list.json",
        "x_content_list_v2.json",
        "x_middle.json",
        "x_model.json",
        "x_origin.docx",
    }
    for name in (*retained, "x_layout.pdf", "x_span.pdf"):
        (nested / name).write_text(name)
    removed = prune_mineru_output(tmp_path)
    assert {path.name for path in nested.iterdir()} == retained
    assert "doc/auto/x_layout.pdf" in removed
    assert "doc/auto/x_span.pdf" in removed


def test_find_parse_dir_accepts_office_profile_and_requires_v2_pair(tmp_path: Path):
    """验证 `find_parse_dir_accepts_office_profile_and_requires_v2_pair` 场景。"""
    decoy = tmp_path / "decoy" / "auto"
    decoy.mkdir(parents=True)
    (decoy / "decoy_middle.json").write_text("{}")
    office = tmp_path / "document" / "office"
    office.mkdir(parents=True)
    (office / "document_middle.json").write_text("{}")
    (office / "document_content_list_v2.json").write_text("[]")

    assert find_parse_dir(tmp_path) == office


def test_materialize_visual_assets_copies_declared_images_and_preserves_hash(tmp_path: Path):
    """验证 `materialize_visual_assets_copies_declared_images_and_preserves_hash` 场景。"""
    source = tmp_path / "mineru" / "images" / "table.jpg"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"jpeg-placeholder")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    document = SimpleNamespace(assets=[SimpleNamespace(path="assets/visual/table.jpg", sha256=digest)])
    bundle = SimpleNamespace(root=tmp_path / "mineru")
    output = tmp_path / "docir"

    materialize_visual_assets(document, bundle, output)

    target = output / "assets/visual/table.jpg"
    assert target.is_file()
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest


def test_aggregate_distinguishes_attempted_and_successful():
    """验证 `aggregate_distinguishes_attempted_and_successful` 场景。"""
    results = [
        {"status": "success", "source_pages": 3, "metrics": {"docir": {"pages": 3, "elements": 10, "unknown_elements": 2}, "strict_audit": {"passed": False}}},
        {"status": "parse_failed", "source_pages": 4},
    ]
    totals = aggregate(results)
    assert totals["documents_total"] == 2
    assert totals["documents_success"] == 1
    assert totals["source_pages_total"] == 7
    assert totals["parsed_pages_total"] == 3
    assert totals["elements_total"] == 10
    assert totals["unknown_elements_total"] == 2
    assert totals["unknown_rate"] == 0.2


def test_resume_does_not_overwrite_verified_success(tmp_path: Path):
    """验证 `resume_does_not_overwrite_verified_success` 场景。"""
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf-placeholder")
    directory = stable_directory_name(source)
    docir_run = tmp_path / "docir"
    result_path = docir_run / directory / "result.json"
    result_path.parent.mkdir(parents=True)
    expected = {"filename": source.name, "status": "success", "sentinel": 1}
    result_path.write_text(json.dumps(expected))
    restored = process_document(source, "run", tmp_path / "mineru", docir_run, 1, True)
    assert restored == expected


@requires_multiformat_fixture
@pytest.mark.parametrize(
    ("name", "filename", "media_type"),
    [
        (
            "docx_mixed",
            "docx_mixed.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "pptx_mixed",
            "pptx_mixed.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        (
            "xlsx_mixed",
            "xlsx_mixed.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ],
)
def test_office_sources_complete_without_inventing_page_semantics(
    tmp_path: Path,
    name: str,
    filename: str,
    media_type: str,
):
    """验证 `office_sources_complete_without_inventing_page_semantics` 场景。"""
    source = MULTIFORMAT_SOURCES / filename
    directory = stable_directory_name(source)
    mineru_run = tmp_path / "mineru"
    shutil.copytree(MULTIFORMAT_OUTPUTS / name, mineru_run / directory)
    docir_run = tmp_path / "docir"

    result = process_document(
        source,
        "stage3",
        mineru_run,
        docir_run,
        timeout=1,
        resume=False,
    )

    assert result["status"] == "success"
    assert result["media_type"] == media_type
    assert result["source_pages"] is None
    assert result["encrypted"] is None
    document = load_document(docir_run / directory / "document.json")
    assert document.pages == ()
    assert document.source_page_count is None
    assert document.elements
    assert all(
        locator.kind == "group"
        and locator.page_id is None
        and locator.bbox is None
        for element in document.elements
        for locator in element.locators
    )
    assert result["removed_mineru_files"] == []
    assert list((mineru_run / directory).rglob(f"*_origin{source.suffix}"))
    assert list((mineru_run / directory).rglob("*_content_list.json"))


@requires_multiformat_fixture
@pytest.mark.parametrize(
    ("name", "filename", "media_type"),
    [
        ("image_document", "image_document.png", "image/png"),
        ("image_scan", "image_scan.jpg", "image/jpeg"),
    ],
)
def test_image_sources_pass_entry_and_keep_source_media_type(
    tmp_path: Path,
    name: str,
    filename: str,
    media_type: str,
):
    """验证 `image_sources_pass_entry_and_keep_source_media_type` 场景。"""
    source = MULTIFORMAT_SOURCES / filename
    directory = stable_directory_name(source)
    mineru_run = tmp_path / "mineru"
    shutil.copytree(MULTIFORMAT_OUTPUTS / name, mineru_run / directory)
    docir_run = tmp_path / "docir"

    result = process_document(
        source,
        "stage3",
        mineru_run,
        docir_run,
        timeout=1,
        resume=False,
    )

    assert result["status"] == "success"
    assert result["media_type"] == media_type
    assert result["source_pages"] == 1
    assert result["encrypted"] is None
    assert len(result["removed_mineru_files"]) == 2
    assert all(
        path.endswith(("_layout.pdf", "_span.pdf"))
        for path in result["removed_mineru_files"]
    )
    assert list((mineru_run / directory).rglob("*_origin.pdf"))
    assert list((mineru_run / directory).rglob("*_content_list.json"))

    document = load_document(docir_run / directory / "document.json")
    assert document.source.media_type == media_type
    original = next(
        asset for asset in document.assets if asset.asset_id == "asset_original"
    )
    assert original.media_type == media_type


@requires_real_fixture
def test_refresh_conversion_reuses_raw_bundle_and_reaudits(tmp_path: Path):
    """验证 `refresh_conversion_reuses_raw_bundle_and_reaudits` 场景。"""
    source = FIXTURE / "assets" / "source.pdf"
    directory = stable_directory_name(source)
    mineru_run = tmp_path / "mineru"
    shutil.copytree(FIXTURE / "raw", mineru_run / directory / "nested")
    docir_run = tmp_path / "docir"
    result_path = docir_run / directory / "result.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(json.dumps({
        "filename": source.name,
        "status": "success",
        "mineru": {"ok": True, "elapsed_seconds": 12.5},
        "metrics": {"raw": {"image_files": 227}},
    }))

    refreshed = process_document(
        source,
        "run",
        mineru_run,
        docir_run,
        1,
        True,
        refresh_conversions=True,
    )

    assert refreshed["status"] == "success"
    assert refreshed["mineru"]["elapsed_seconds"] == 12.5
    assert refreshed["metrics"]["raw"]["generated_image_files"] == 227
    assert refreshed["metrics"]["strict_audit"] == {"passed": True, "error": None}
