# backend/agent/DocIR/core/elements.py

"""

这个文件干什么：DocIR V0.2 判别联合内容元素。

直白点说就是：定义标题、段落、列表、表格、公式、图片和代码等不同内容块长什么样。

DocIR V0.2 判别联合内容元素。
"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .enums import ElementRole
from .geometry import Region, StrictModel
from .text import TextContent


class ElementBase(StrictModel):
    element_id: str = Field(min_length=1)
    document_order: int = Field(ge=0)
    role: ElementRole = ElementRole.BODY
    section_id: str | None = None
    regions: tuple[Region, ...]
    text: TextContent | None = None
    parent_element_id: str | None = None
    caption_element_ids: tuple[str, ...] = ()
    footnote_element_ids: tuple[str, ...] = ()
    quality_issue_ids: tuple[str, ...] = ()
    source_type: str | None = None

    @model_validator(mode="after")
    def needs_region(self) -> "ElementBase":
        if not self.regions:
            raise ValueError("element 至少需要一个 Region")
        return self


class HeadingElement(ElementBase):
    kind: Literal["heading"] = "heading"
    level: int = Field(ge=1, le=6)


class ParagraphElement(ElementBase):
    kind: Literal["paragraph"] = "paragraph"


class ListElement(ElementBase):
    kind: Literal["list"] = "list"
    ordered: bool | None = None
    items: tuple[str, ...] = ()


class TableElement(ElementBase):
    kind: Literal["table"] = "table"
    html: str | None = None
    asset_id: str | None = None


class FormulaElement(ElementBase):
    kind: Literal["formula"] = "formula"
    latex: str | None = None
    asset_id: str | None = None


class FigureElement(ElementBase):
    kind: Literal["figure"] = "figure"
    asset_id: str | None = None


class CodeElement(ElementBase):
    kind: Literal["code"] = "code"
    language: str | None = None


class UnknownElement(ElementBase):
    kind: Literal["unknown"] = "unknown"
    raw_type: str
    raw_payload: dict | None = None


Element = Annotated[
    HeadingElement
    | ParagraphElement
    | ListElement
    | TableElement
    | FormulaElement
    | FigureElement
    | CodeElement
    | UnknownElement,
    Field(discriminator="kind"),
]
