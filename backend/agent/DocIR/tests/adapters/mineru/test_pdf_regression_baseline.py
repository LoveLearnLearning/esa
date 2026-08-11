"""真实 PDF → MinerU bundle → DocIR → Chunk/Evidence 回归基线。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from backend.agent.DocIR.adapters.mineru import convert_bundle, file_sha256, load_bundle
from backend.agent.DocIR.io import load_document, save_document
from backend.agent.DocIR.paths import WORKSPACE_ROOT
from backend.agent.rag.chunk import ChunkBuilder
from backend.agent.rag.retrieval.context import EvidenceAssembler

BASELINE_PATH = Path(__file__).with_name("pdf_regression_baseline.json")
DOCIR_ROOT = Path(__file__).resolve().parents[3]
LOCAL_SOURCE_ROOT = DOCIR_ROOT / "mineru_adapter_samples"
LOCAL_OUTPUT_ROOT = (
    Path(__file__).resolve().parents[2] / "fixtures/mineru_adapter/outputs"
)
if (
    not BASELINE_PATH.is_file()
    or not LOCAL_SOURCE_ROOT.is_dir()
    or not LOCAL_OUTPUT_ROOT.is_dir()
):
    pytest.skip(
        "external PDF/MinerU regression data is unavailable",
        allow_module_level=True,
    )

BASELINE = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
LOCAL_DOCUMENTS = BASELINE["local_documents"]
DOCUMENTS = BASELINE["documents"]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}

MINERU_RUN = Path(
    os.environ.get(
        "DOCIR_PDF_BASELINE_MINERU_RUN",
        WORKSPACE_ROOT / "artifacts/mineru/runs" / BASELINE["run_id"],
    )
)
SOURCE_ROOT = Path(
    os.environ.get(
        "DOCIR_PDF_BASELINE_SOURCE_ROOT",
        WORKSPACE_ROOT / "documents/reference_paper/pdf",
    )
)

requires_pdf_baseline = pytest.mark.skipif(
    not MINERU_RUN.is_dir() or not SOURCE_ROOT.is_dir(),
    reason=(
        "external PDF regression corpus is unavailable; set "
        "DOCIR_PDF_BASELINE_MINERU_RUN and DOCIR_PDF_BASELINE_SOURCE_ROOT"
    ),
)


def _parse_dir(case: dict[str, object]) -> Path:
    case_root = MINERU_RUN / str(case["directory"])
    matches = sorted({path.parent for path in case_root.rglob("*_middle.json")})
    assert len(matches) == 1, (
        f"expected one MinerU bundle under {case_root}, got {matches}"
    )
    return matches[0]


def _actual_metrics(
    case: dict[str, object],
    tmp_path: Path,
    *,
    source: Path,
    parse_dir: Path,
    require_strict_alignment: bool = False,
) -> dict[str, int]:
    assert source.is_file(), f"missing PDF baseline source: {source}"
    assert file_sha256(source) == case["source_sha256"]

    bundle = load_bundle(parse_dir)
    assert bundle.middle.version_name == BASELINE["mineru_version"]
    assert bundle.middle.backend == BASELINE["backend"]
    document = convert_bundle(bundle, source, source_page_count=int(case["pages"]))
    if require_strict_alignment:
        strict_document = convert_bundle(
            bundle,
            source,
            source_page_count=int(case["pages"]),
            strict=True,
        )
        assert len(strict_document.elements) == len(document.elements)

    snapshot = tmp_path / "document.json"
    save_document(document, snapshot)
    reloaded = load_document(snapshot)
    assert reloaded == document
    assert reloaded.schema_name == "docir"
    assert reloaded.source.media_type == "application/pdf"
    assert reloaded.source.sha256 == case["source_sha256"]
    assert not any(element.kind == "unknown" for element in reloaded.elements)
    assert not any(
        issue.code == "visual_asset_missing" for issue in reloaded.quality_issues
    )

    chunk_document = ChunkBuilder().build(
        reloaded,
        docir_sha256=file_sha256(snapshot),
    )
    evidence = tuple(
        item
        for chunk in chunk_document.chunks
        for item in EvidenceAssembler.build(chunk, reloaded.source.filename)
    )

    return {
        "pages": len(reloaded.pages),
        "raw_middle_blocks": sum(
            len(page.para_blocks) for page in bundle.middle.pdf_info
        ),
        "raw_discarded_blocks": sum(
            len(page.discarded_blocks) for page in bundle.middle.pdf_info
        ),
        "raw_v2_blocks": sum(
            len(page) for page in bundle.content_v2 if isinstance(page, list)
        ),
        "raw_image_files": sum(
            path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
            for path in bundle.root.rglob("*")
        ),
        "elements": len(reloaded.elements),
        "sections": len(reloaded.sections),
        "assets": len(reloaded.assets),
        "figures": sum(element.kind == "figure" for element in reloaded.elements),
        "tables": sum(element.kind == "table" for element in reloaded.elements),
        "visual_assets": sum(
            asset.kind.value in {"figure", "table"} for asset in reloaded.assets
        ),
        "quality_issues": len(reloaded.quality_issues),
        "chunks": len(chunk_document.chunks),
        "evidence_occurrences": len(evidence),
        "unique_evidence": len({item.evidence_id for item in evidence}),
    }


@pytest.mark.parametrize(
    "case",
    LOCAL_DOCUMENTS,
    ids=[item["name"] for item in LOCAL_DOCUMENTS],
)
def test_local_pdf_fixtures_match_regression_baseline(
    case: dict[str, object], tmp_path: Path
):
    output_root = LOCAL_OUTPUT_ROOT / str(case["name"])
    matches = sorted({path.parent for path in output_root.rglob("*_middle.json")})
    assert len(matches) == 1, f"expected one local MinerU bundle under {output_root}"
    expected = {
        key: value
        for key, value in case.items()
        if key not in {"name", "filename", "source_sha256"}
    }
    assert (
        _actual_metrics(
            case,
            tmp_path,
            source=LOCAL_SOURCE_ROOT / str(case["filename"]),
            parse_dir=matches[0],
            require_strict_alignment=True,
        )
        == expected
    )


@requires_pdf_baseline
@pytest.mark.parametrize(
    "case", DOCUMENTS, ids=[item["directory"] for item in DOCUMENTS]
)
def test_pdf_pipeline_matches_regression_baseline(
    case: dict[str, object], tmp_path: Path
):
    expected = {
        key: value
        for key, value in case.items()
        if key
        not in {
            "directory",
            "filename",
            "source_sha256",
        }
    }
    assert (
        _actual_metrics(
            case,
            tmp_path,
            source=SOURCE_ROOT / str(case["filename"]),
            parse_dir=_parse_dir(case),
        )
        == expected
    )


def test_pdf_regression_manifest_totals_are_internally_consistent():
    metric_names = set(BASELINE["totals"]) - {"documents"}
    actual = {
        name: sum(int(document[name]) for document in DOCUMENTS)
        for name in metric_names
    }
    assert len(DOCUMENTS) == BASELINE["totals"]["documents"]
    assert actual == {name: BASELINE["totals"][name] for name in metric_names}
