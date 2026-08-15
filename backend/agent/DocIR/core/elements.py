# backend/agent/DocIR/core/elements.py

"""

这个文件干什么：DocIR 判别联合内容元素。

直白点说就是：定义标题、段落、列表、表格、公式、图片和代码等不同内容块长什么样。

DocIR 判别联合内容元素。
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, JsonValue

from .enums import ElementRole
from .geometry import Locator, StrictModel
from .text import TextContent


class ElementProvenance(StrictModel):
    """Element 到 parser 原始产物中位置的轻量可回查锚点。"""

    artifact_id: str = Field(min_length=1)
    json_path: str | None = None
    group_index: int | None = Field(default=None, ge=0)
    block_index: int | None = Field(default=None, ge=0)
    source_anchor: str | None = None


class ElementBase(StrictModel):
    """封装 `ElementBase` 的状态与行为。"""
    element_id: str = Field(min_length=1)
    document_order: int = Field(ge=0)
    role: ElementRole = ElementRole.BODY
    section_id: str | None = None
    locators: tuple[Locator, ...] = ()
    provenance: tuple[ElementProvenance, ...] = ()
    text: TextContent | None = None
    parent_element_id: str | None = None
    caption_element_ids: tuple[str, ...] = ()
    footnote_element_ids: tuple[str, ...] = ()
    quality_issue_ids: tuple[str, ...] = ()
    source_type: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    enrichment_revision_id: str | None = None
    related_asset_ids: tuple[str, ...] = ()


class HeadingElement(ElementBase):
    """封装 `HeadingElement` 的状态与行为。"""
    kind: Literal["heading"] = "heading"
    # Parser 没有明确给出标题级别时保持 None；DocIR 不根据字号、编号或
    # 相邻标题猜测层级。
    level: int | None = Field(default=None, ge=1, le=6)


class ParagraphElement(ElementBase):
    """封装 `ParagraphElement` 的状态与行为。"""
    kind: Literal["paragraph"] = "paragraph"


class ListElement(ElementBase):
    """封装 `ListElement` 的状态与行为。"""
    kind: Literal["list"] = "list"
    ordered: bool | None = None
    items: tuple[str, ...] = ()


class TableElement(ElementBase):
    """封装 `TableElement` 的状态与行为。"""
    kind: Literal["table"] = "table"
    html: str | None = None
    asset_id: str | None = None


class FormulaElement(ElementBase):
    """封装 `FormulaElement` 的状态与行为。"""
    kind: Literal["formula"] = "formula"
    latex: str | None = None
    asset_id: str | None = None


class FigureElement(ElementBase):
    """封装 `FigureElement` 的状态与行为。"""
    kind: Literal["figure"] = "figure"
    asset_id: str | None = None
    structured_content: str | None = None


class CodeElement(ElementBase):
    """封装 `CodeElement` 的状态与行为。"""
    kind: Literal["code"] = "code"
    language: str | None = None


class UnknownElement(ElementBase):
    """封装 `UnknownElement` 的状态与行为。"""
    kind: Literal["unknown"] = "unknown"
    raw_type: str
    raw_payload: dict | None = None


Element = Annotated[
    Union[
        HeadingElement,
        ParagraphElement,
        ListElement,
        TableElement,
        FormulaElement,
        FigureElement,
        CodeElement,
        UnknownElement,
    ],
    Field(discriminator="kind"),
]
