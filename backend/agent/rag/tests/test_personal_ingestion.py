"""Native personal ingestion and format-specific locator contracts."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.agent.DocIR.core import Locator, NormalizedBox, normalize_bbox
from backend.agent.rag.personal import (
    LOCATOR_SCHEMA_VERSION,
    PersonalKnowledgeBaseIngestion,
)


class _UnusedMinerU:
    configuration_fingerprint = "f" * 64

    def parse(self, _source: Path, _output_root: Path):
        raise AssertionError("native sources must not call MinerU")


@pytest.mark.parametrize(
    ("filename", "content", "kind"),
    [
        ("notes.txt", "first line\nsecond line\n", "text_lines"),
        ("notes.md", "# Graphs\n\nDijkstra finds shortest paths.\n", "markdown_section"),
        ("rows.csv", "name,value\nalpha,1\nbeta,2\n", "csv_rows"),
        ("data.json", '{"course":{"name":"algorithms"}}', "json_pointer"),
    ],
)
def test_native_formats_produce_docir_chunks_and_versioned_locators(
    tmp_path, filename, content, kind
):
    source = tmp_path / filename
    source.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    ingestion = PersonalKnowledgeBaseIngestion(
        tmp_path / "artifacts", mineru_parser=_UnusedMinerU()
    )
    result = asyncio.run(
        ingestion.ingest(
            file_id="12345678-1234-5678-1234-567812345678",
            filename=filename,
            media_type="text/plain",
            source_path=source,
            source_sha256=digest,
        )
    )
    assert result.manifest_path.is_file()
    assert result.chunks.chunks
    locators = [
        locator
        for chunk in result.chunks.chunks
        for evidence in chunk.evidence
        for locator in evidence.locators
    ]
    assert locators
    assert {locator.kind for locator in locators} == {kind}
    assert {locator.schema_version for locator in locators} == {
        LOCATOR_SCHEMA_VERSION
    }
    for current_root, _directories, files in os.walk(result.artifact_root):
        current = Path(current_root)
        if os.name == "posix":
            assert current.stat().st_uid == os.geteuid()
            assert current.stat().st_mode & 0o777 == 0o700
        for name in files:
            if os.name == "posix":
                assert (current / name).stat().st_mode & 0o777 == 0o600


def test_personal_locator_rejects_missing_or_invalid_required_fields():
    with pytest.raises(ValidationError):
        Locator(
            locator_id="bad-lines",
            kind="text_lines",
            schema_version=LOCATOR_SCHEMA_VERSION,
            start_line=2,
            end_line=1,
        )
    with pytest.raises(ValidationError):
        Locator(
            locator_id="bad-pointer",
            kind="json_pointer",
            schema_version=LOCATOR_SCHEMA_VERSION,
            pointer="not/a/pointer",
        )


def test_all_personal_locator_schemas_enforce_ranges_and_normalized_geometry():
    bbox = normalize_bbox((10, 20, 60, 70), width=100, height=100)
    assert bbox == NormalizedBox(x0=0.1, y0=0.2, x1=0.6, y1=0.7)
    locators = (
        Locator(
            locator_id="text", kind="text_lines",
            schema_version=LOCATOR_SCHEMA_VERSION, start_line=1, end_line=2,
        ),
        Locator(
            locator_id="markdown", kind="markdown_section",
            schema_version=LOCATOR_SCHEMA_VERSION, start_line=1, end_line=4,
            heading_path=("Root",),
        ),
        Locator(
            locator_id="csv", kind="csv_rows",
            schema_version=LOCATOR_SCHEMA_VERSION, start_row=1, end_row=3,
            columns=("name", "value"),
        ),
        Locator(
            locator_id="json", kind="json_pointer",
            schema_version=LOCATOR_SCHEMA_VERSION, pointer="/a~1b/~0value",
        ),
        Locator(
            locator_id="pdf", kind="pdf_region",
            schema_version=LOCATOR_SCHEMA_VERSION, page=1, bbox=bbox,
        ),
        Locator(
            locator_id="image", kind="image_region",
            schema_version=LOCATOR_SCHEMA_VERSION, asset_id="asset-1",
            ocr_region="region-1", bbox=bbox,
        ),
        Locator(
            locator_id="office", kind="mineru_section",
            schema_version=LOCATOR_SCHEMA_VERSION, group_id="group-1",
            section_path=("Sheet 1",), page=1, bbox=bbox,
        ),
    )

    assert {value.kind for value in locators} == {
        "text_lines", "markdown_section", "csv_rows", "json_pointer",
        "pdf_region", "image_region", "mineru_section",
    }
    assert all(value.schema_version == LOCATOR_SCHEMA_VERSION for value in locators)
    assert all(
        value.page is None or value.page >= 1
        for value in locators
    )
    with pytest.raises(ValidationError):
        Locator(
            locator_id="zero-page", kind="pdf_region",
            schema_version=LOCATOR_SCHEMA_VERSION, page=0, bbox=bbox,
        )
