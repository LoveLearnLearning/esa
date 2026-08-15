# backend/agent/DocIR/tests/core/test_document.py

"""验证当前唯一 DocIR contract 的内容、定位和引用不变量。"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.agent.DocIR.core.document import (
    Asset,
    Document,
    Page,
    PageRange,
    ParseRevision,
    SourceVersion,
    ValidationSummary,
)
from backend.agent.DocIR.core.elements import ElementProvenance, ParagraphElement
from backend.agent.DocIR.core.enums import AssetKind, TextOrigin, ValidationStatus
from backend.agent.DocIR.core.geometry import Locator, NormalizedBox, normalize_bbox
from backend.agent.DocIR.core.text import TextContent, TextLayer

HASH = "a" * 64


def make_document(*, with_page: bool = True) -> Document:
    """处理 `make_document` 相关逻辑。

    Args:
        with_page: bool => `with_page` 参数。

    Returns:
        Document => 处理结果。
    """
    asset = Asset(
        asset_id="original",
        kind=AssetKind.ORIGINAL,
        path="assets/source.pdf",
        media_type="application/pdf",
        byte_size=10,
        sha256=HASH,
    )
    pages = (
        Page(
            page_id="p5",
            page_index=5,
            display_page_no=6,
            width=100,
            height=200,
            unit="pt",
        ),
    ) if with_page else ()
    locators = (
        Locator(
            locator_id="l1",
            kind="page",
            container_id="p5",
            container_index=5,
            page_id="p5",
            bbox=NormalizedBox(x0=.1, y0=.1, x1=.9, y1=.2),
        ),
    ) if with_page else ()
    text = TextContent(
        primary_layer_id="t1",
        layers=(TextLayer(text_layer_id="t1", origin=TextOrigin.UNKNOWN, text="正文"),),
    )
    element = ParagraphElement(
        element_id="e1",
        document_order=0,
        locators=locators,
        text=text,
    )
    return Document(
        document_id="d1",
        created_at=datetime.now(timezone.utc),
        source=SourceVersion(
            source_version_id="s1",
            filename="source.pdf",
            media_type="application/pdf",
            byte_size=10,
            sha256=HASH,
            original_asset_id="original",
        ),
        parse_revision=ParseRevision(
            parse_revision_id="pr1",
            parser_name="test",
            parser_version="1",
            page_range=PageRange(start=5, end=5) if with_page else None,
            config_sha256=HASH,
        ),
        source_page_count=30 if with_page else None,
        parsed_page_count=len(pages),
        pages=pages,
        elements=(element,),
        assets=(asset,),
        validation=ValidationSummary(status=ValidationStatus.PASSED),
    )


def test_document_and_element_without_pages_or_locators_are_valid() -> None:
    """验证 `document_and_element_without_pages_or_locators_are_valid` 场景。"""
    document = make_document(with_page=False)
    assert document.pages == ()
    assert document.elements[0].locators == ()


def test_pdf_page_and_bbox_locator_are_preserved() -> None:
    """验证 `pdf_page_and_bbox_locator_are_preserved` 场景。"""
    document = make_document()
    locator = document.elements[0].locators[0]
    assert locator.page_id == "p5"
    assert locator.bbox is not None
    assert document.pages[0].display_page_no == 6


def test_normalize_bbox_clips_parser_coordinates_to_page_bounds() -> None:
    """验证 `normalize_bbox_clips_parser_coordinates_to_page_bounds` 场景。"""
    bbox = normalize_bbox((-1, -2, 100.2, 201), width=100, height=200)
    assert bbox == NormalizedBox(x0=0, y0=0, x1=1, y1=1)


def test_unknown_text_cannot_be_quote_eligible() -> None:
    """验证 `unknown_text_cannot_be_quote_eligible` 场景。"""
    with pytest.raises(ValidationError, match="不可标记"):
        TextLayer(text_layer_id="t", origin=TextOrigin.UNKNOWN, text="x", quote_eligible=True)


def test_pages_are_rejected_not_silently_sorted() -> None:
    """验证 `pages_are_rejected_not_silently_sorted` 场景。"""
    document = make_document()
    page6 = Page(page_id="p6", page_index=6, width=100, height=200)
    with pytest.raises(ValidationError, match="严格递增"):
        Document.model_validate({
            **document.model_dump(),
            "parsed_page_count": 2,
            "pages": [page6, document.pages[0]],
            "parse_revision": {
                **document.parse_revision.model_dump(),
                "page_range": {"start": 5, "end": 6},
            },
        })


def test_locator_page_reference_must_exist() -> None:
    """验证 `locator_page_reference_must_exist` 场景。"""
    document = make_document(with_page=False)
    locator = Locator(locator_id="bad", kind="page", page_id="missing")
    element = document.elements[0].model_copy(update={"locators": (locator,)})
    with pytest.raises(ValidationError, match="Locator.page_id"):
        Document.model_validate({**document.model_dump(), "elements": [element]})


def test_element_provenance_artifact_reference_must_exist() -> None:
    """验证 `element_provenance_artifact_reference_must_exist` 场景。"""
    document = make_document(with_page=False)
    provenance = ElementProvenance(artifact_id="missing", group_index=0, block_index=1)
    element = document.elements[0].model_copy(update={"provenance": (provenance,)})
    with pytest.raises(ValidationError, match="provenance"):
        Document.model_validate({**document.model_dump(), "elements": [element]})


def test_duplicate_element_id_has_a_specific_error() -> None:
    """验证 `duplicate_element_id_has_a_specific_error` 场景。"""
    document = make_document(with_page=False)
    duplicate = document.elements[0].model_copy(update={"document_order": 1})
    with pytest.raises(ValidationError, match="element_id 不能重复"):
        Document.model_validate({
            **document.model_dump(),
            "elements": [document.elements[0], duplicate],
        })
