# backend/agent/DocIR/tests/core/test_v02_document.py

"""

这个文件干什么：验证 DocIR V0.2 文档模型的关键数据约束和跨对象引用规则。

直白点说就是：故意构造正确和错误的文档，确认 V0.2 不会悄悄接受乱序、重复编号或失效引用。
"""

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
from backend.agent.DocIR.core.elements import ParagraphElement
from backend.agent.DocIR.core.enums import AssetKind, TextOrigin, ValidationStatus
from backend.agent.DocIR.core.geometry import NormalizedBox, Region
from backend.agent.DocIR.core.text import TextContent, TextLayer

HASH = "a" * 64


def make_document(page_index=5):
    asset = Asset(asset_id="original", kind=AssetKind.ORIGINAL, path="assets/source.pdf", media_type="application/pdf", byte_size=10, sha256=HASH)
    page = Page(page_id="p5", page_index=page_index, display_page_no=page_index + 1, width=100, height=200)
    text = TextContent(primary_layer_id="t1", layers=(TextLayer(text_layer_id="t1", origin=TextOrigin.UNKNOWN, text="正文"),))
    element = ParagraphElement(element_id="e1", document_order=0, regions=(Region(region_id="r1", page_id="p5", bbox=NormalizedBox(x0=.1, y0=.1, x1=.9, y1=.2)),), text=text)
    return Document(document_id="d1", created_at=datetime.now(timezone.utc), source=SourceVersion(source_version_id="s1", filename="source.pdf", media_type="application/pdf", byte_size=10, sha256=HASH, original_asset_id="original"), parse_revision=ParseRevision(parse_revision_id="pr1", parser_name="test", parser_version="1", page_range=PageRange(start=5, end=5), config_sha256=HASH), source_page_count=30, parsed_page_count=1, pages=(page,), elements=(element,), assets=(asset,), validation=ValidationSummary(status=ValidationStatus.PASSED))


def test_partial_parse_preserves_original_page_index():
    document = make_document(5)
    assert document.source_page_count == 30
    assert document.pages[0].display_page_no == 6


def test_unknown_text_cannot_be_quote_eligible():
    with pytest.raises(ValidationError, match="不可标记"):
        TextLayer(text_layer_id="t", origin=TextOrigin.UNKNOWN, text="x", quote_eligible=True)


def test_native_or_ocr_unverified_is_a_distinct_non_quotable_origin():
    layer = TextLayer(
        text_layer_id="t",
        origin=TextOrigin.NATIVE_OR_OCR_UNVERIFIED,
        text="无法证明来源的文字",
    )
    assert layer.origin.value == "native_or_ocr_unverified"
    with pytest.raises(ValidationError, match="unverified"):
        TextLayer(
            text_layer_id="t",
            origin=TextOrigin.NATIVE_OR_OCR_UNVERIFIED,
            text="x",
            quote_eligible=True,
        )


def test_pages_are_rejected_not_silently_sorted():
    document = make_document(5)
    page6 = Page(page_id="p6", page_index=6, display_page_no=7, width=100, height=200)
    with pytest.raises(ValidationError, match="严格递增"):
        Document.model_validate({**document.model_dump(), "parsed_page_count": 2, "pages": [page6, document.pages[0]], "parse_revision": {**document.parse_revision.model_dump(), "page_range": {"start": 5, "end": 6}}})


def test_duplicate_element_id_has_a_specific_error():
    document = make_document(5)
    duplicate = document.elements[0].model_copy(update={"document_order": 1})
    with pytest.raises(ValidationError, match="element_id 不能重复"):
        Document.model_validate({**document.model_dump(), "elements": [document.elements[0], duplicate]})


def test_formula_can_reference_a_visual_asset():
    document = make_document(5)
    formula_asset = Asset(
        asset_id="formula-image",
        kind=AssetKind.FIGURE,
        path="assets/formula.png",
        media_type="image/png",
        byte_size=10,
        sha256=HASH,
        page_id="p5",
        region_id="r1",
    )
    formula = {
        **document.elements[0].model_dump(),
        "kind": "formula",
        "latex": "x^2",
        "asset_id": "formula-image",
    }
    validated = Document.model_validate(
        {**document.model_dump(), "elements": [formula], "assets": [document.assets[0], formula_asset]}
    )
    assert validated.elements[0].kind == "formula"
    assert validated.elements[0].asset_id == "formula-image"


def test_element_asset_reference_must_exist():
    document = make_document(5)
    formula = {
        **document.elements[0].model_dump(),
        "kind": "formula",
        "latex": "x^2",
        "asset_id": "missing",
    }
    with pytest.raises(ValidationError, match="Element.asset_id 引用了不存在的资产"):
        Document.model_validate({**document.model_dump(), "elements": [formula]})
