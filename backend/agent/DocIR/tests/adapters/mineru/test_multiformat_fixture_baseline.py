# backend/agent/DocIR/tests/adapters/mineru/test_multiformat_fixture_baseline.py

"""MinerU 3.4.4 多格式原始输出的结构差异基线。"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

BASELINE_PATH = Path(__file__).with_name("multiformat_fixture_baseline.json")
DOCIR_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = DOCIR_ROOT / "mineru_adapter_samples"
OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "fixtures/mineru_adapter/outputs"
if not BASELINE_PATH.is_file() or not SOURCE_ROOT.is_dir() or not OUTPUT_ROOT.is_dir():
    pytest.skip(
        "external multiformat MinerU regression data is unavailable",
        allow_module_level=True,
    )

BASELINE = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
DOCUMENTS = BASELINE["documents"]


def _sha256(path: Path) -> str:
    """处理 `_sha256` 相关逻辑。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _exactly_one(root: Path, pattern: str) -> Path:
    """处理 `_exactly_one` 相关逻辑。"""
    matches = sorted(root.rglob(pattern))
    assert len(matches) == 1, f"expected one {pattern} under {root}, got {matches}"
    return matches[0]


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


def _all_strings(value: Any) -> list[str]:
    """处理 `_all_strings` 相关逻辑。"""
    strings: list[str] = []
    if isinstance(value, str):
        strings.append(value)
    elif isinstance(value, dict):
        for child in value.values():
            strings.extend(_all_strings(child))
    elif isinstance(value, list):
        for child in value:
            strings.extend(_all_strings(child))
    return strings


def _actual(case: dict[str, Any]) -> dict[str, Any]:
    """处理 `_actual` 相关逻辑。"""
    name = case["name"]
    output = OUTPUT_ROOT / name
    middle_path = _exactly_one(output, "*_middle.json")
    bundle = middle_path.parent
    v2_path = _exactly_one(output, "*_content_list_v2.json")
    v1_path = _exactly_one(output, "*_content_list.json")
    model_path = _exactly_one(output, "*_model.json")
    origin_path = _exactly_one(output, "*_origin.*")

    middle = json.loads(middle_path.read_text(encoding="utf-8"))
    v2 = json.loads(v2_path.read_text(encoding="utf-8"))
    v1 = json.loads(v1_path.read_text(encoding="utf-8"))
    model = json.loads(model_path.read_text(encoding="utf-8"))

    assert isinstance(middle.get("pdf_info"), list)
    assert isinstance(v2, list) and all(isinstance(page, list) for page in v2)
    assert isinstance(v1, list)
    assert isinstance(model, list)

    pages = middle["pdf_info"]
    middle_blocks = [
        block
        for page in pages
        for block in page.get("para_blocks", [])
    ]
    discarded_blocks = [
        block
        for page in pages
        for block in page.get("discarded_blocks", [])
    ]
    v2_blocks = [block for page in v2 for block in page]
    asset_paths = [
        path for path in _values_for_key(v2, "path") if isinstance(path, str)
    ]

    for asset_path in asset_paths:
        if asset_path:
            assert (bundle / asset_path).is_file(), (
                f"missing referenced asset for {name}: {asset_path}"
            )

    searchable_text = "\n".join(_all_strings(v2))
    for marker in case["markers"]:
        assert marker in searchable_text, f"missing marker for {name}: {marker}"

    model_page_shapes = sorted({type(page).__name__ for page in model})
    return {
        "bundle_profile": bundle.name,
        "reported_backend": middle.get("_backend"),
        "pages": len(pages),
        "page_indices": [page.get("page_idx") for page in pages],
        "pages_with_size": sum("page_size" in page for page in pages),
        "middle_blocks": len(middle_blocks),
        "middle_types": dict(sorted(Counter(
            block.get("type") for block in middle_blocks
        ).items())),
        "discarded_blocks": len(discarded_blocks),
        "v2_blocks": len(v2_blocks),
        "v2_types": dict(sorted(Counter(
            block.get("type") for block in v2_blocks
        ).items())),
        "middle_blocks_with_bbox": sum("bbox" in block for block in middle_blocks),
        "v2_blocks_with_bbox": sum("bbox" in block for block in v2_blocks),
        "v1_blocks": len(v1),
        "v1_blocks_with_page_idx": sum("page_idx" in block for block in v1),
        "anchor_fields": len(_values_for_key(middle, "anchor"))
        + len(_values_for_key(v2, "anchor")),
        "asset_paths": asset_paths,
        "model_page_shapes": model_page_shapes,
        "origin_suffix": origin_path.suffix.lower(),
        "output_file_count": sum(path.is_file() for path in output.rglob("*")),
    }


@pytest.mark.parametrize("case", DOCUMENTS, ids=[case["name"] for case in DOCUMENTS])
def test_multiformat_raw_output_matches_baseline(case: dict[str, Any]):
    """验证 `multiformat_raw_output_matches_baseline` 场景。"""
    source = SOURCE_ROOT / case["filename"]
    assert source.is_file()
    assert _sha256(source) == case["source_sha256"]

    expected = {
        key: value
        for key, value in case.items()
        if key
        not in {
            "name",
            "format",
            "filename",
            "source_sha256",
            "markers",
        }
    }
    assert _actual(case) == expected
    middle_path = _exactly_one(OUTPUT_ROOT / case["name"], "*_middle.json")
    middle = json.loads(middle_path.read_text(encoding="utf-8"))
    assert middle["_version_name"] == BASELINE["mineru_version"]


def test_multiformat_baseline_covers_requested_formats():
    """验证 `multiformat_baseline_covers_requested_formats` 场景。"""
    assert {case["format"] for case in DOCUMENTS} == {
        "PDF",
        "DOCX",
        "PPTX",
        "XLSX",
        "PNG",
        "JPG",
    }
