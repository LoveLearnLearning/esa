from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from backend.agent.DocIR.io import load_document
from backend.agent.rag.chunk import ChunkBuilder

from ..api import materialize_bundle
from ..bundle import PaddleOCRBundle, load_bundle
from ..converter import convert_bundle


def _png() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (200, 300), "white").save(stream, format="PNG")
    return stream.getvalue()


def _page(*, unknown: bool = False) -> dict:
    blocks = [
        {
            "block_label": "doc_title",
            "block_content": "Document title",
            "block_bbox": [10, 10, 190, 30],
            "block_id": 0,
            "block_order": 1,
        },
        {
            "block_label": "paragraph_title",
            "block_content": "Heading without level",
            "block_bbox": [10, 40, 190, 60],
            "block_id": 1,
            "block_order": 2,
        },
        {
            "block_label": "text",
            "block_content": "Body text",
            "block_bbox": [10, 70, 190, 90],
            "block_id": 2,
            "block_order": 3,
        },
        {
            "block_label": "table",
            "block_content": "<table><tr><td>A</td><td>B</td></tr></table>",
            "block_bbox": [10, 100, 190, 160],
            "block_id": 3,
            "block_order": None,
        },
        {
            "block_label": "formula",
            "block_content": "x^2",
            "block_bbox": [10, 170, 90, 200],
            "block_id": 4,
            "block_order": 4,
        },
        {
            "block_label": "image",
            "block_content": "",
            "block_bbox": [100, 170, 190, 240],
            "block_id": 5,
            "block_order": 5,
        },
        {
            "block_label": "figure_title",
            "block_content": "Figure 1",
            "block_bbox": [100, 245, 190, 265],
            "block_id": 6,
            "block_order": 6,
        },
    ]
    if unknown:
        blocks.append(
            {
                "block_label": "future_label",
                "block_content": "future",
                "block_bbox": [10, 270, 190, 290],
                "block_id": 7,
                "block_order": 7,
            }
        )
    ocr_boxes = [block["block_bbox"] for block in blocks if block["block_content"]]
    return {
        "input_path": "fixture.png",
        "page_index": None,
        "page_count": None,
        "width": 200,
        "height": 300,
        "model_settings": {},
        "parsing_res_list": blocks,
        "layout_det_res": {
            "boxes": [
                {
                    "label": block["block_label"],
                    "score": 0.95,
                    "coordinate": block["block_bbox"],
                }
                for block in blocks
            ]
        },
        "overall_ocr_res": {
            "rec_boxes": ocr_boxes,
            "rec_scores": [0.9] * len(ocr_boxes),
        },
        "table_res_list": [
            {
                "pred_html": "<table><tr><td>A</td><td>B</td></tr></table>",
                "cell_box_list": [[10, 100, 90, 160], [90, 100, 190, 160]],
                "table_ocr_pred": {
                    "rec_scores": [0.98, 0.97],
                    "rec_boxes": [[10, 100, 90, 160], [90, 100, 190, 160]],
                },
            }
        ],
    }


def _bundle(*, status: str = "success", unknown: bool = False) -> PaddleOCRBundle:
    return PaddleOCRBundle(
        pages=(_page(unknown=unknown),),
        page_images=(_png(),),
        status=status,
        version={
            "paddleocr": "3.7.0",
            "paddlex": "3.7.2",
            "paddlepaddle_gpu": "3.3.0",
        },
        config={
            "low_confidence_threshold": 0.5,
            "layout_detection_model_name": "PP-DocLayout_plus-L",
            "text_recognition_model_name": "PP-OCRv5_server_rec",
        },
    )


def test_semantics_geometry_confidence_and_assets(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(_png())
    document = convert_bundle(_bundle(), source)
    assert [element.kind for element in document.elements] == [
        "heading",
        "heading",
        "paragraph",
        "table",
        "formula",
        "figure",
        "paragraph",
    ]
    assert document.title == "Document title"
    assert document.elements[0].level == 1
    assert document.elements[1].level is None
    assert document.elements[3].html == "<table><tr><td>A</td><td>B</td></tr></table>"
    assert document.elements[3].asset_id is not None
    assert document.elements[4].latex == "x^2"
    assert document.elements[5].asset_id is not None
    assert document.elements[6].role.value == "caption"
    locator = document.elements[2].locators[0]
    assert locator.bbox.x0 == pytest.approx(0.05)
    assert locator.bbox.y0 == pytest.approx(70 / 300)
    layer = document.elements[2].text.layers[0]
    assert layer.origin.value == "ocr_text"
    assert layer.confidence == pytest.approx(0.9)
    assert layer.quote_eligible is False
    assert len(document.sections) == 2
    assert document.validation.status.value == "passed_with_warnings"


def test_status_and_unknown_policy(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(_png())
    with pytest.raises(ValueError, match="status"):
        convert_bundle(_bundle(status="failure"), source)
    lenient = convert_bundle(_bundle(unknown=True), source)
    assert lenient.elements[-1].kind == "unknown"
    with pytest.raises(ValueError, match="future_label"):
        convert_bundle(_bundle(unknown=True), source, strict=True)


def test_atomic_materialization_reload_replay_and_chunking(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(_png())
    output = tmp_path / "converted"
    original = materialize_bundle(_bundle(), source, output)
    reloaded = load_document(output / "document.json")
    assert reloaded == original
    for asset in reloaded.assets:
        content = (output / asset.path).read_bytes()
        assert hashlib.sha256(content).hexdigest() == asset.sha256
    replayed = convert_bundle(load_bundle(output), source)
    assert replayed.document_id == original.document_id
    assert replayed.elements == original.elements
    assert len(ChunkBuilder().build(reloaded, docir_sha256="0" * 64).chunks) > 0
    with pytest.raises(FileExistsError):
        materialize_bundle(_bundle(), source, output)


def test_page_and_image_count_must_match() -> None:
    with pytest.raises(ValueError, match="数量不一致"):
        PaddleOCRBundle(
            pages=(_page(),),
            page_images=(),
            status="success",
            version={},
            config={},
        )
