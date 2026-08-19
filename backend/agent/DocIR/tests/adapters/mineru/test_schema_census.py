# backend/agent/DocIR/tests/adapters/mineru/test_schema_census.py

"""Regression tests for the raw MinerU cross-format schema census."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.agent.DocIR.tools.inspect_mineru_schema import (
    build_census,
    default_fixtures,
    scan_value,
)


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures/mineru_adapter/outputs"
BASELINE_PATH = Path(__file__).with_name("multiformat_schema_census.json")
requires_multiformat_fixture = pytest.mark.skipif(
    not FIXTURE_ROOT.is_dir(),
    reason="external multiformat MinerU regression data is unavailable",
)
requires_schema_baseline = pytest.mark.skipif(
    not BASELINE_PATH.is_file(),
    reason="external MinerU schema census baseline is unavailable",
)


def test_scan_value_canonicalizes_arrays_and_tracks_parent_presence() -> None:
    """验证 `scan_value_canonicalizes_arrays_and_tracks_parent_presence` 场景。"""
    scan = scan_value(
        {
            "items": [
                {"value": 1},
                {"value": "two"},
                {"nullable": None},
                {"value": ""},
            ],
            "empty_items": [],
            "empty_object": {},
        }
    )

    assert "items[].value" in scan.observations
    assert not any("[0]" in path or "[1]" in path for path in scan.observations)
    value = scan.materialize("items[].value")
    assert value["count"] == 3
    assert value["parent_count"] == 4
    assert value["missing_count"] == 1
    assert value["presence_ratio"] == 0.75
    assert value["types"] == {"integer": 1, "string": 2}
    assert value["multiple_types"] is True
    assert value["empty_string_count"] == 1

    nullable = scan.materialize("items[].nullable")
    assert nullable["null_count"] == 1
    assert nullable["missing_count"] == 3
    absent = scan.materialize("items[].absent")
    assert absent["count"] == 0
    assert absent["parent_count"] == 4
    assert absent["presence_ratio"] == 0.0

    empty = scan.materialize("empty_items")
    assert empty["empty_array_count"] == 1
    empty_elements = scan.materialize("empty_items[]")
    assert empty_elements["count"] == 0
    assert empty_elements["parent_count"] == 1
    assert empty_elements["presence_ratio"] == 0.0
    assert scan.materialize("empty_object")["empty_object_count"] == 1


@requires_multiformat_fixture
def test_fixed_fixture_census_detects_pipeline_office_schema_differences() -> None:
    """验证 `fixed_fixture_census_detects_pipeline_office_schema_differences` 场景。"""
    census = build_census(default_fixtures(FIXTURE_ROOT))

    assert census["formats"] == ["PDF", "DOCX", "PPTX", "XLSX", "PNG", "JPG"]
    assert census["mineru_versions_observed"] == ["3.4.4"]
    assert census["backend_profiles"] == {
        "office": ["DOCX", "PPTX", "XLSX"],
        "pipeline": ["JPG", "PDF", "PNG"],
    }

    page_size = census["json_paths"]["middle"]["pdf_info[].page_size"]
    bbox = census["json_paths"]["middle"]["pdf_info[].para_blocks[].bbox"]
    assert page_size["present_formats"] == ["PDF", "PNG", "JPG"]
    assert bbox["present_formats"] == ["PDF", "PNG", "JPG"]
    assert page_size["pipeline_only"] is True
    assert bbox["formats"]["DOCX"]["count"] == 0
    assert bbox["formats"]["DOCX"]["parent_count"] == 18
    assert bbox["formats"]["DOCX"]["missing_count"] == 18

    model_shapes = census["shapes"]["model"]
    assert model_shapes["PDF"]["group_item_types"] == ["object"]
    assert model_shapes["PNG"]["group_item_types"] == ["object"]
    assert model_shapes["DOCX"]["group_item_types"] == ["array"]
    assert model_shapes["PPTX"]["group_item_types"] == ["array"]
    assert model_shapes["XLSX"]["group_item_types"] == ["array"]
    assert census["json_paths"]["model"]["[][].content"]["formats"]["DOCX"][
        "multiple_types"
    ] is True


@requires_multiformat_fixture
def test_block_type_aggregation_distinguishes_missing_from_empty_chart_path() -> None:
    """验证 `block_type_aggregation_distinguishes_missing_from_empty_chart_path` 场景。"""
    census = build_census(default_fixtures(FIXTURE_ROOT))
    v2_types = census["block_types"]["content_list_v2"]

    assert {"chart", "image", "list", "paragraph", "table", "title"} <= set(v2_types)
    pptx_chart = v2_types["chart"]["formats"]["PPTX"]
    xlsx_chart = v2_types["chart"]["formats"]["XLSX"]
    for chart in (pptx_chart, xlsx_chart):
        path = chart["fields"]["content.image_source.path"]
        assert path["count"] == 1
        assert path["missing_count"] == 0
        assert path["empty_string_count"] == 1
        assert path["presence_ratio"] == 1.0
        assert chart["fields"]["content.content"]["count"] == 1

    pdf_chart_path = v2_types["chart"]["formats"]["PDF"]["fields"][
        "content.image_source.path"
    ]
    assert pdf_chart_path["empty_string_count"] == 0
    assert pdf_chart_path["examples"][0].startswith("images/")

    docx_list = v2_types["list"]["formats"]["DOCX"]
    assert docx_list["fields"]["content.attribute"]["count"] == 1
    assert docx_list["fields"]["content.list_items[].ilevel"]["count"] == 3


@requires_multiformat_fixture
def test_artifact_inventory_detects_pipeline_and_office_outputs() -> None:
    """验证 `artifact_inventory_detects_pipeline_and_office_outputs` 场景。"""
    census = build_census(default_fixtures(FIXTURE_ROOT))
    matrix = census["artifact_inventory"]["matrix"]

    for artifact in (
        "middle.json",
        "content_list.json",
        "content_list_v2.json",
        "model.json",
        "markdown",
    ):
        assert matrix[artifact]["all_formats"] is True
    assert matrix["layout.pdf"]["pipeline_only"] is True
    assert matrix["span.pdf"]["pipeline_only"] is True
    assert matrix["origin.pdf"]["pipeline_only"] is True
    assert matrix["origin.docx"]["counts"]["DOCX"] == 1
    assert matrix["origin.pptx"]["counts"]["PPTX"] == 1
    assert matrix["origin.xlsx"]["counts"]["XLSX"] == 1
    assert matrix["image_asset.jpg"]["counts"]["XLSX"] == 0


@requires_multiformat_fixture
@requires_schema_baseline
def test_fixed_fixture_census_matches_machine_readable_baseline() -> None:
    """验证 `fixed_fixture_census_matches_machine_readable_baseline` 场景。"""
    expected = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    actual = build_census(default_fixtures(FIXTURE_ROOT))
    assert actual == expected
