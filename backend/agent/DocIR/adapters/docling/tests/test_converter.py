"""Pure DoclingDocument-to-DocIR conversion tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from docling_core.types.doc import (
    BoundingBox,
    ContentLayer,
    CoordOrigin,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    Size,
    TableCell,
    TableData,
)

from backend.agent.DocIR.adapters.docling import (
    DoclingBundle,
    convert_bundle,
    load_bundle,
    materialize_bundle,
)
from backend.agent.DocIR.io import load_document
from backend.agent.rag.chunk import ChunkBuilder
from backend.agent.rag.chunk.serializer import file_sha256


def _prov(
    bbox: tuple[float, float, float, float],
    origin: CoordOrigin = CoordOrigin.TOPLEFT,
) -> ProvenanceItem:
    return ProvenanceItem(
        page_no=1,
        bbox=BoundingBox.from_tuple(bbox, origin=origin),
        charspan=(0, 4),
    )


def _document() -> DoclingDocument:
    document = DoclingDocument(name="fixture")
    document.add_page(page_no=1, size=Size(width=100, height=100))
    document.add_title("Title", prov=_prov((10, 10, 90, 20)))
    document.add_heading("Section", level=2, prov=_prov((10, 90, 60, 70), CoordOrigin.BOTTOMLEFT))
    document.add_text(
        DocItemLabel.TEXT,
        "Body text",
        prov=_prov((10, 30, 90, 40)),
    )
    group = document.add_list_group(name="ordered")
    document.add_list_item("First", enumerated=True, marker="1.", parent=group)
    document.add_list_item("Second", enumerated=True, marker="2.", parent=group)
    document.add_formula("x^2")
    document.add_code("print('ok')")
    table = TableData(
        num_rows=1,
        num_cols=1,
        table_cells=[
            TableCell(
                start_row_offset_idx=0,
                end_row_offset_idx=1,
                start_col_offset_idx=0,
                end_col_offset_idx=1,
                text="Cell",
            )
        ],
    )
    document.add_table(table, prov=_prov((10, 50, 90, 70)))
    caption = document.add_text(
        DocItemLabel.CAPTION,
        "Figure caption",
        content_layer=ContentLayer.BODY,
    )
    document.add_picture(caption=caption, prov=_prov((10, 72, 50, 90)))
    return document


def _bundle(status: str = "success") -> DoclingBundle:
    return DoclingBundle(
        document=_document(),
        status=status,
        version={"docling_version": "2.114.0", "docling_core_version": "2.91.0"},
        config={"device": "cuda", "do_ocr": True},
        errors=({"component_type": "test", "error_message": "partial"},)
        if status == "partial_success"
        else (),
    )


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-synthetic-source")
    return source


def test_semantic_types_sections_and_coordinates(tmp_path: Path) -> None:
    document = convert_bundle(_bundle(), _source(tmp_path), strict=True)

    assert [element.kind for element in document.elements] == [
        "heading",
        "heading",
        "paragraph",
        "list",
        "formula",
        "code",
        "table",
        "paragraph",
        "figure",
    ]
    assert document.elements[3].items == ("First", "Second")
    assert document.elements[3].ordered is True
    assert document.elements[6].html == "<table><tbody><tr><td>Cell</td></tr></tbody></table>"
    assert document.elements[8].caption_element_ids == (document.elements[7].element_id,)
    locator = document.elements[1].locators[0]
    assert locator.metadata["docling_coord_origin"] == "BOTTOMLEFT"
    assert locator.bbox.y0 == pytest.approx(0.1)
    assert locator.bbox.y1 == pytest.approx(0.3)
    assert document.parse_revision.parser_name == "Docling"
    assert document.parse_revision.parser_version == "2.114.0"
    assert document.parsed_page_count == 1
    assert len(document.sections) == 3


def test_partial_success_policy(tmp_path: Path) -> None:
    source = _source(tmp_path)
    document = convert_bundle(_bundle("partial_success"), source)
    assert document.validation.status.value == "passed_with_warnings"
    assert document.quality_issues[0].code == "docling_partial_success"
    with pytest.raises(ValueError, match="partial_success"):
        convert_bundle(_bundle("partial_success"), source, strict=True)


def test_failure_is_never_consumable(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="status=failure"):
        convert_bundle(_bundle("failure"), _source(tmp_path))


def test_atomic_bundle_round_trip_and_chunking(tmp_path: Path) -> None:
    source = _source(tmp_path)
    output = tmp_path / "output"
    materialize_bundle(_bundle(), source, output, strict=True)

    document_path = output / "document.json"
    document = load_document(document_path)
    replayed = convert_bundle(load_bundle(output), source, strict=True)
    assert replayed.document_id == document.document_id
    assert [element.kind for element in replayed.elements] == [
        element.kind for element in document.elements
    ]
    for asset in document.assets:
        assert (output / asset.path).is_file()
        assert file_sha256(output / asset.path) == asset.sha256
    chunked = ChunkBuilder().build(document, docir_sha256=file_sha256(document_path))
    assert chunked.chunks
    assert len(chunked.element_dispositions) == len(document.elements)
    with pytest.raises(FileExistsError):
        materialize_bundle(_bundle(), source, output)

