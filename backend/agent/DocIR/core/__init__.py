# backend/agent/DocIR/core/__init__.py

"""

这个文件干什么：DocIR 正式核心类型的显式公共入口。

直白点说就是：把 DocIR 最常用的数据类型集中导出，让调用方从一个地方拿齐。

DocIR 正式核心类型的显式公共入口。
"""

from .document import (
    Asset,
    Document,
    EnrichmentRevision,
    ModelReference,
    Page,
    PageRange,
    ParseRevision,
    PrintedPageNumber,
    QualityIssue,
    Section,
    SourceVersion,
    ValidationSummary,
)
from .elements import (
    CodeElement,
    Element,
    ElementBase,
    ElementProvenance,
    FigureElement,
    FormulaElement,
    HeadingElement,
    ListElement,
    ParagraphElement,
    TableElement,
    UnknownElement,
)
from .enums import AssetKind, ElementRole, Severity, TextOrigin, ValidationStatus
from .geometry import (
    CoordinateTransform,
    NormalizedBox,
    Point,
    Locator,
    SourceGeometry,
    StrictModel,
    normalize_bbox,
)
from .text import InlineSpan, TextContent, TextLayer

__all__ = [
    "Asset",
    "AssetKind",
    "CodeElement",
    "CoordinateTransform",
    "Document",
    "EnrichmentRevision",
    "Element",
    "ElementBase",
    "ElementProvenance",
    "ElementRole",
    "FigureElement",
    "FormulaElement",
    "HeadingElement",
    "InlineSpan",
    "ListElement",
    "ModelReference",
    "NormalizedBox",
    "Page",
    "PageRange",
    "ParagraphElement",
    "ParseRevision",
    "Point",
    "PrintedPageNumber",
    "QualityIssue",
    "Locator",
    "Section",
    "Severity",
    "SourceGeometry",
    "SourceVersion",
    "StrictModel",
    "TableElement",
    "TextContent",
    "TextLayer",
    "TextOrigin",
    "UnknownElement",
    "ValidationStatus",
    "ValidationSummary",
    "normalize_bbox",
]
