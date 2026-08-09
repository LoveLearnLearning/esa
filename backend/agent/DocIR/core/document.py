# backend/agent/DocIR/core/document.py

"""
这个文件干什么：DocIR V0.2 顶层快照与跨对象不变量。

直白点说就是：规定一整份 DocIR 文档由哪些对象组成，并检查页码、元素、章节和资源之间是否互相对得上。

DocIR V0.2 顶层快照与跨对象不变量。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from .elements import Element, ElementBase
from .enums import AssetKind, Severity, TextOrigin, ValidationStatus
from .geometry import CoordinateTransform, NormalizedBox, StrictModel

SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PageRange(StrictModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> "PageRange":
        if self.end < self.start:
            raise ValueError("page_range.end 必须不小于 start")
        return self


class ModelReference(StrictModel):
    name: str
    version: str | None = None
    sha256: str | None = None

    @field_validator("sha256")
    @classmethod
    def hash_format(cls, value: str | None) -> str | None:
        if value is not None and not SHA256.fullmatch(value):
            raise ValueError("模型 sha256 格式错误")
        return value


class SourceVersion(StrictModel):
    source_version_id: str
    filename: str
    media_type: str
    byte_size: int = Field(gt=0)
    sha256: str
    original_asset_id: str

    @field_validator("sha256")
    @classmethod
    def source_hash(cls, value: str) -> str:
        if not SHA256.fullmatch(value):
            raise ValueError("source sha256 必须为 64 位小写十六进制")
        return value


class ParseRevision(StrictModel):
    parse_revision_id: str
    parser_name: str
    parser_version: str
    backend: str | None = None
    method: str | None = None
    language_hints: tuple[str, ...] = ()
    page_range: PageRange
    config: dict[str, JsonValue] = Field(default_factory=dict)
    config_sha256: str
    models: tuple[ModelReference, ...] = ()
    started_at: datetime | None = None
    completed_at: datetime | None = None
    raw_artifact_ids: tuple[str, ...] = ()

    @field_validator("config_sha256")
    @classmethod
    def config_hash(cls, value: str) -> str:
        if not SHA256.fullmatch(value):
            raise ValueError("config_sha256 格式错误")
        return value


class PrintedPageNumber(StrictModel):
    text: str
    origin: TextOrigin
    confidence: float | None = Field(default=None, ge=0, le=1)
    region_id: str | None = None


class Page(StrictModel):
    page_id: str
    page_index: int = Field(ge=0)
    display_page_no: int = Field(ge=1)
    page_label: str | None = None
    printed_page: PrintedPageNumber | None = None
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    unit: Literal["pt"] = "pt"
    rotation_degrees: Literal[0, 90, 180, 270] = 0
    crop_box: NormalizedBox | None = None
    page_image_asset_id: str | None = None
    transforms: tuple[CoordinateTransform, ...] = ()
    quality_issue_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def display_number(self) -> "Page":
        if self.display_page_no != self.page_index + 1:
            raise ValueError("display_page_no 必须等于 page_index + 1")
        return self


class Section(StrictModel):
    section_id: str
    parent_section_id: str | None = None
    title_element_id: str | None = None
    element_ids: tuple[str, ...] = ()


class Asset(StrictModel):
    asset_id: str
    kind: AssetKind
    path: str
    media_type: str
    byte_size: int = Field(ge=0)
    sha256: str
    page_id: str | None = None
    region_id: str | None = None
    quality_issue_ids: tuple[str, ...] = ()

    @field_validator("path")
    @classmethod
    def relative_safe_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or not value.strip():
            raise ValueError("asset.path 必须是安全的相对 POSIX 路径")
        return value

    @field_validator("sha256")
    @classmethod
    def asset_hash(cls, value: str) -> str:
        if not SHA256.fullmatch(value):
            raise ValueError("asset sha256 格式错误")
        return value


class QualityIssue(StrictModel):
    issue_id: str
    code: str
    severity: Severity = Severity.WARNING
    message: str
    object_id: str | None = None


class ValidationSummary(StrictModel):
    status: ValidationStatus
    issue_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class _DocumentIndex:
    """一次构建的引用索引，供各项文档级规则共享。"""

    page_ids: frozenset[str]
    element_by_id: dict[str, ElementBase]
    region_ids: frozenset[str]
    asset_ids: frozenset[str]
    section_by_id: dict[str, Section]
    issue_ids: frozenset[str]


class Document(StrictModel):
    schema_name: Literal["docir"] = "docir"
    schema_version: Literal["0.2"] = "0.2"
    document_id: str
    created_at: datetime
    source: SourceVersion
    parse_revision: ParseRevision
    title: str | None = None
    languages: tuple[str, ...] = ()
    source_page_count: int = Field(ge=1)
    parsed_page_count: int = Field(ge=1)
    pages: tuple[Page, ...]
    sections: tuple[Section, ...] = ()
    elements: tuple[Element, ...]
    assets: tuple[Asset, ...]
    quality_issues: tuple[QualityIssue, ...] = ()
    validation: ValidationSummary

    @model_validator(mode="after")
    def global_invariants(self) -> "Document":
        index = _build_document_index(self)
        _validate_page_invariants(self, index)
        _validate_element_invariants(self, index)
        _validate_asset_invariants(self, index)
        _validate_section_invariants(self, index)
        _validate_element_relations(self, index)
        _validate_quality_invariants(self, index)
        return self


def _require_unique(values: list[str] | list[int], message: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(message)


def _build_document_index(document: Document) -> _DocumentIndex:
    elements = {element.element_id: element for element in document.elements}
    return _DocumentIndex(
        page_ids=frozenset(page.page_id for page in document.pages),
        element_by_id=elements,
        region_ids=frozenset(region.region_id for element in document.elements for region in element.regions),
        asset_ids=frozenset(asset.asset_id for asset in document.assets),
        section_by_id={section.section_id: section for section in document.sections},
        issue_ids=frozenset(issue.issue_id for issue in document.quality_issues),
    )


def _validate_page_invariants(document: Document, index: _DocumentIndex) -> None:
    if document.parsed_page_count != len(document.pages):
        raise ValueError("parsed_page_count 必须等于 pages 的数量")
    if document.source_page_count < document.parsed_page_count:
        raise ValueError("source_page_count 不能小于 parsed_page_count")

    page_ids = [page.page_id for page in document.pages]
    page_indexes = [page.page_index for page in document.pages]
    _require_unique(page_ids, "page_id 不能重复")
    _require_unique(page_indexes, "page_index 不能重复")
    if page_indexes != sorted(page_indexes):
        raise ValueError("pages 必须按原始 page_index 严格递增")
    if any(page_index >= document.source_page_count for page_index in page_indexes):
        raise ValueError("page_index 超出 source_page_count")
    page_range = document.parse_revision.page_range
    if any(page_index < page_range.start or page_index > page_range.end for page_index in page_indexes):
        raise ValueError("page_index 超出 parse_revision.page_range")


def _validate_element_invariants(document: Document, index: _DocumentIndex) -> None:
    element_ids = [element.element_id for element in document.elements]
    _require_unique(element_ids, "element_id 不能重复")
    orders = [element.document_order for element in document.elements]
    if orders != list(range(len(orders))):
        raise ValueError("document_order 必须从 0 连续递增")

    region_ids = [region.region_id for element in document.elements for region in element.regions]
    _require_unique(region_ids, "region_id 不能重复")
    if any(region.page_id not in index.page_ids for element in document.elements for region in element.regions):
        raise ValueError("Region.page_id 引用了不存在的页面")


def _validate_asset_invariants(document: Document, index: _DocumentIndex) -> None:
    asset_ids = [asset.asset_id for asset in document.assets]
    _require_unique(asset_ids, "asset_id 不能重复")
    original_id = document.source.original_asset_id
    if original_id not in index.asset_ids:
        raise ValueError("source.original_asset_id 引用了不存在的资产")
    original_asset = next(asset for asset in document.assets if asset.asset_id == original_id)
    if original_asset.kind != AssetKind.ORIGINAL:
        raise ValueError("source.original_asset_id 必须引用 original 类型资产")
    if any(asset_id not in index.asset_ids for asset_id in document.parse_revision.raw_artifact_ids):
        raise ValueError("parse_revision.raw_artifact_ids 引用了不存在的资产")
    if any(asset.page_id is not None and asset.page_id not in index.page_ids for asset in document.assets):
        raise ValueError("Asset.page_id 引用了不存在的页面")
    if any(asset.region_id is not None and asset.region_id not in index.region_ids for asset in document.assets):
        raise ValueError("Asset.region_id 引用了不存在的区域")

    for element in document.elements:
        linked_asset_ids: tuple[str | None, ...] = ()
        if hasattr(element, "asset_id"):
            linked_asset_ids = (element.asset_id,)
        if any(asset_id is not None and asset_id not in index.asset_ids for asset_id in linked_asset_ids):
            raise ValueError(f"Element.asset_id 引用了不存在的资产: {element.element_id}")


def _validate_section_invariants(document: Document, index: _DocumentIndex) -> None:
    section_ids = [section.section_id for section in document.sections]
    _require_unique(section_ids, "section_id 不能重复")
    if not document.sections:
        if any(element.section_id is not None for element in document.elements):
            raise ValueError("没有 Section 时 Element.section_id 必须为空")
        return

    roots = [section for section in document.sections if section.parent_section_id is None]
    if len(roots) != 1:
        raise ValueError("Section 必须形成单根树")
    if any(
        section.parent_section_id is not None and section.parent_section_id not in index.section_by_id
        for section in document.sections
    ):
        raise ValueError("Section.parent_section_id 引用了不存在的章节")

    for section in document.sections:
        _validate_section_chain(section, index)
        _require_unique(list(section.element_ids), f"Section.element_ids 不能重复: {section.section_id}")
        if any(element_id not in index.element_by_id for element_id in section.element_ids):
            raise ValueError(f"Section.element_ids 引用了不存在的元素: {section.section_id}")
        if section.title_element_id is not None and section.title_element_id not in index.element_by_id:
            raise ValueError(f"Section.title_element_id 引用了不存在的元素: {section.section_id}")

    for element in document.elements:
        if element.section_id is None:
            continue
        if element.section_id not in index.section_by_id:
            raise ValueError(f"Element.section_id 引用了不存在的章节: {element.element_id}")
        if element.element_id not in index.section_by_id[element.section_id].element_ids:
            raise ValueError(f"Element.section_id 与 Section.element_ids 不一致: {element.element_id}")


def _validate_section_chain(section: Section, index: _DocumentIndex) -> None:
    seen: set[str] = set()
    cursor = section
    while cursor.parent_section_id is not None:
        if cursor.section_id in seen:
            raise ValueError(f"Section 树存在环: {section.section_id}")
        seen.add(cursor.section_id)
        cursor = index.section_by_id[cursor.parent_section_id]


def _validate_element_relations(document: Document, index: _DocumentIndex) -> None:
    for element in document.elements:
        _require_unique(
            list(element.caption_element_ids),
            f"Element.caption_element_ids 不能重复: {element.element_id}",
        )
        _require_unique(
            list(element.footnote_element_ids),
            f"Element.footnote_element_ids 不能重复: {element.element_id}",
        )
        if element.parent_element_id is not None:
            _validate_element_reference(element, element.parent_element_id, "parent_element_id", index)
        for reference in element.caption_element_ids:
            _validate_element_reference(element, reference, "caption_element_ids", index)
        for reference in element.footnote_element_ids:
            _validate_element_reference(element, reference, "footnote_element_ids", index)
        _validate_parent_chain(element, index)


def _validate_element_reference(
    owner: ElementBase,
    reference: str,
    field_name: str,
    index: _DocumentIndex,
) -> None:
    if reference == owner.element_id:
        raise ValueError(f"Element.{field_name} 不能自引用: {owner.element_id}")
    if reference not in index.element_by_id:
        raise ValueError(f"Element.{field_name} 引用了不存在的元素: {owner.element_id}")


def _validate_parent_chain(element: ElementBase, index: _DocumentIndex) -> None:
    seen: set[str] = set()
    cursor = element
    while cursor.parent_element_id is not None:
        if cursor.element_id in seen:
            raise ValueError(f"Element parent 链存在环: {element.element_id}")
        seen.add(cursor.element_id)
        cursor = index.element_by_id[cursor.parent_element_id]


def _validate_quality_invariants(document: Document, index: _DocumentIndex) -> None:
    issue_ids = [issue.issue_id for issue in document.quality_issues]
    _require_unique(issue_ids, "quality_issues.issue_id 不能重复")
    if any(issue_id not in index.issue_ids for issue_id in document.validation.issue_ids):
        raise ValueError("validation.issue_ids 引用了不存在的质量问题")

    object_issue_refs = [issue for page in document.pages for issue in page.quality_issue_ids]
    object_issue_refs.extend(issue for element in document.elements for issue in element.quality_issue_ids)
    object_issue_refs.extend(issue for asset in document.assets for issue in asset.quality_issue_ids)
    if any(issue_id not in index.issue_ids for issue_id in object_issue_refs):
        raise ValueError("对象的 quality_issue_ids 引用了不存在的质量问题")
    if document.validation.status == ValidationStatus.FAILED:
        raise ValueError("validation.status=failed 的文档不能构造成可消费快照")
