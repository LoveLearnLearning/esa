# backend/agent/DocIR/tests/tools/test_batch_corpus.py

"""

这个文件干什么：验证 PDF 批处理流水线的发现、保留、恢复、校验和汇总规则。

直白点说就是：模拟批量处理 PDF 的各种情况，确认断点续跑、文件裁剪、图片复制和统计报告都按规则工作。
"""

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from backend.agent.DocIR.tools.batch_corpus import (
    aggregate,
    discover_pdfs,
    materialize_visual_assets,
    process_document,
    prune_mineru_output,
    should_retain,
    stable_directory_name,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mineru_3_4_4_text_page"


def test_discover_pdfs_is_sorted_and_case_insensitive(tmp_path: Path):
    (tmp_path / "b.PDF").write_bytes(b"b")
    (tmp_path / "a.pdf").write_bytes(b"a")
    (tmp_path / "note.txt").write_text("x")
    assert [path.name for path in discover_pdfs(tmp_path)] == ["a.pdf", "b.PDF"]


def test_stable_directory_name_uses_hash_and_safe_stem(tmp_path: Path):
    path = tmp_path / "报告.pdf"
    path.write_bytes(b"content")
    digest = hashlib.sha256(b"content").hexdigest()
    assert stable_directory_name(path) == f"{digest[:12]}--报告"


def test_retention_policy_is_exact():
    assert should_retain(Path("x_middle.json"))
    assert should_retain(Path("x_content_list_v2.json"))
    assert should_retain(Path("x_model.json"))
    assert should_retain(Path("x.md"))
    assert should_retain(Path("images/table.JPG"))
    assert should_retain(Path("images/figure.png"))
    assert not should_retain(Path("x_content_list.json"))
    assert not should_retain(Path("x_layout.pdf"))


def test_prune_removes_debug_and_keeps_structural_files(tmp_path: Path):
    nested = tmp_path / "doc" / "auto"
    nested.mkdir(parents=True)
    for name in ("x.md", "x_middle.json", "x_content_list_v2.json", "x_model.json", "figure.jpg", "x_layout.pdf", "x_content_list.json"):
        (nested / name).write_text(name)
    removed = prune_mineru_output(tmp_path)
    assert sorted(path.name for path in nested.iterdir()) == ["figure.jpg", "x.md", "x_content_list_v2.json", "x_middle.json", "x_model.json"]
    assert "doc/auto/x_layout.pdf" in removed


def test_materialize_visual_assets_copies_declared_images_and_preserves_hash(tmp_path: Path):
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


def test_refresh_conversion_reuses_raw_bundle_and_reaudits(tmp_path: Path):
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
