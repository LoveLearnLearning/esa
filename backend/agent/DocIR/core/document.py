# backend/agent/DocIR/core/document.py

"""
这个文件干什么：DocIR 顶层快照与跨对象不变量。

直白点说就是：规定一整份 DocIR 文档由哪些对象组成，并检查页码、元素、章节和资源之间是否互相对得上。

DocIR 顶层快照与跨对象不变量。
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
    """封装 `PageRange` 的状态与行为。"""
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> "PageRange":
        """处理 `ordered` 相关逻辑。"""
        if self.end < self.start:
            raise ValueError("page_range.end 必须不小于 start")
        return self


class ModelReference(StrictModel):
    """封装 `ModelReference` 的状态与行为。"""
    name: str
    version: str | None = None
    sha256: str | None = None

    @field_validator("sha256")
    @classmethod
    def hash_format(cls, value: str | None) -> str | None:
        """处理 `hash_format` 相关逻辑。"""
        if value is not None and not SHA256.fullmatch(value):
            raise ValueError("模型 sha256 格式错误")
        return value


class SourceVersion(StrictModel):
    """封装 `SourceVersion` 的状态与行为。"""
    source_version_id: str
    filename: str
    media_type: str
    byte_size: int = Field(gt=0)
    sha256: str
    original_asset_id: str

    @field_validator("sha256")
    @classmethod
    def source_hash(cls, value: str) -> str:
        """处理 `source_hash` 相关逻辑。"""
        if not SHA256.fullmatch(value):
            raise ValueError("source sha256 必须为 64 位小写十六进制")
        return value


class ParseRevision(StrictModel):
    """封装 `ParseRevision` 的状态与行为。"""
    parse_revision_id: str
    parser_name: str
    parser_version: str
    backend: str | None = None
    method: str | None = None
    language_hints: tuple[str, ...] = ()
    page_range: PageRange | None = None
    config: dict[str, JsonValue] = Field(default_factory=dict)
    config_sha256: str
    models: tuple[ModelReference, ...] = ()
    started_at: datetime | None = None
    completed_at: datetime | None = None
    raw_artifact_ids: tuple[str, ...] = ()

    @field_validator("config_sha256")
    @classmethod
    def config_hash(cls, value: str) -> str:
        """处理 `config_hash` 相关逻辑。"""
        if not SHA256.fullmatch(value):
            raise ValueError("config_sha256 格式错误")
        return value


class EnrichmentRevision(StrictModel):
    """一次可审计的模型派生内容生成记录。"""

    enrichment_revision_id: str
    kind: Literal["vlm_description"] = "vlm_description"
    provider: str
    model_name: str
    model_revision: str | None = None
    prompt_sha256: str
    asset_sha256s: tuple[str, ...] = ()

    @field_validator("prompt_sha256")
    @classmethod
    def prompt_hash(cls, value: str) -> str:
        """处理 `prompt_hash` 相关逻辑。"""
        if not SHA256.fullmatch(value):
            raise ValueError("prompt_sha256 格式错误")
        return value

    @field_validator("asset_sha256s")
    @classmethod
    def asset_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """处理 `asset_hashes` 相关逻辑。"""
        if any(not SHA256.fullmatch(value) for value in values):
            raise ValueError("asset_sha256s 包含无效 SHA-256")
        if len(values) != len(set(values)):
            raise ValueError("asset_sha256s 不能重复")
        return values


class PrintedPageNumber(StrictModel):
    """封装 `PrintedPageNumber` 的状态与行为。"""
    text: str
    origin: TextOrigin
    confidence: float | None = Field(default=None, ge=0, le=1)
    locator_id: str | None = None


class Page(StrictModel):
    """封装 `Page` 的状态与行为。"""
    page_id: str
    page_index: int = Field(ge=0)
    display_page_no: int | None = Field(default=None, ge=1)
    page_label: str | None = None
    printed_page: PrintedPageNumber | None = None
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    unit: str | None = None
    rotation_degrees: Literal[0, 90, 180, 270] = 0
    crop_box: NormalizedBox | None = None
    page_image_asset_id: str | None = None
    transforms: tuple[CoordinateTransform, ...] = ()
    quality_issue_ids: tuple[str, ...] = ()

class Section(StrictModel):
    """封装 `Section` 的状态与行为。"""
    section_id: str
    parent_section_id: str | None = None
    title_element_id: str | None = None
    element_ids: tuple[str, ...] = ()


class Asset(StrictModel):
    """封装 `Asset` 的状态与行为。"""
    asset_id: str
    kind: AssetKind
    path: str
    media_type: str
    byte_size: int = Field(ge=0)
    sha256: str
    locator_ids: tuple[str, ...] = ()
    quality_issue_ids: tuple[str, ...] = ()

    @field_validator("path")
    @classmethod
    def relative_safe_path(cls, value: str) -> str:
        """处理 `relative_safe_path` 相关逻辑。"""
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or not value.strip():
            raise ValueError("asset.path 必须是安全的相对 POSIX 路径")
        return value

    @field_validator("sha256")
    @classmethod
    def asset_hash(cls, value: str) -> str:
        """处理 `asset_hash` 相关逻辑。"""
        if not SHA256.fullmatch(value):
            raise ValueError("asset sha256 格式错误")
        return value


class QualityIssue(StrictModel):
    """封装 `QualityIssue` 的状态与行为。"""
    issue_id: str
    code: str
    severity: Severity = Severity.WARNING
    message: str
    object_id: str | None = None


class ValidationSummary(StrictModel):
    """封装 `ValidationSummary` 的状态与行为。"""
    status: ValidationStatus
    issue_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class _DocumentIndex:
    """一次构建的引用索引，供各项文档级规则共享。"""

    page_ids: frozenset[str]
    element_by_id: dict[str, ElementBase]
    locator_ids: frozenset[str]
    asset_ids: frozenset[str]
    section_by_id: dict[str, Section]
    issue_ids: frozenset[str]


class Document(StrictModel):
    """封装 `Document` 的状态与行为。"""
    schema_name: Literal["docir"] = "docir"
    document_id: str
    created_at: datetime
    source: SourceVersion
    parse_revision: ParseRevision
    enrichment_revisions: tuple[EnrichmentRevision, ...] = ()
    title: str | None = None
    languages: tuple[str, ...] = ()
    source_page_count: int | None = Field(default=None, ge=1)
    parsed_page_count: int = Field(default=0, ge=0)
    pages: tuple[Page, ...] = ()
    sections: tuple[Section, ...] = ()
    elements: tuple[Element, ...]
    assets: tuple[Asset, ...]
    quality_issues: tuple[QualityIssue, ...] = ()
    validation: ValidationSummary

    @model_validator(mode="after")
    def global_invariants(self) -> "Document":
        """处理 `global_invariants` 相关逻辑。"""
        index = _build_document_index(self)
        _validate_page_invariants(self, index)
        _validate_element_invariants(self, index)
        _validate_asset_invariants(self, index)
        _validate_section_invariants(self, index)
        _validate_element_relations(self, index)
        _validate_quality_invariants(self, index)
        return self


def _require_unique(values: list[str] | list[int], message: str) -> None:
    """处理 `_require_unique` 相关逻辑。"""
    if len(values) != len(set(values)):
        raise ValueError(message)


def _build_document_index(document: Document) -> _DocumentIndex:
    """构建 `document index` 相关数据。"""
    elements = {element.element_id: element for element in document.elements}
    return _DocumentIndex(
        page_ids=frozenset(page.page_id for page in document.pages),
        element_by_id=elements,
        locator_ids=frozenset(
            locator.locator_id for element in document.elements for locator in element.locators
        ),
        asset_ids=frozenset(asset.asset_id for asset in document.assets),
        section_by_id={section.section_id: section for section in document.sections},
        issue_ids=frozenset(issue.issue_id for issue in document.quality_issues),
    )


def _validate_page_invariants(document: Document, index: _DocumentIndex) -> None:
    """校验 `page invariants` 相关数据。"""
    if document.parsed_page_count != len(document.pages):
        raise ValueError("parsed_page_count 必须等于 pages 的数量")
    if document.source_page_count is not None and document.source_page_count < document.parsed_page_count:
        raise ValueError("source_page_count 不能小于 parsed_page_count")

    page_ids = [page.page_id for page in document.pages]
    page_indexes = [page.page_index for page in document.pages]
    _require_unique(page_ids, "page_id 不能重复")
    _require_unique(page_indexes, "page_index 不能重复")
    if page_indexes != sorted(page_indexes):
        raise ValueError("pages 必须按原始 page_index 严格递增")
    if document.source_page_count is not None and any(
        page_index >= document.source_page_count for page_index in page_indexes
    ):
        raise ValueError("page_index 超出 source_page_count")
    page_range = document.parse_revision.page_range
    if page_range is not None and any(
        page_index < page_range.start or page_index > page_range.end
        for page_index in page_indexes
    ):
        raise ValueError("page_index 超出 parse_revision.page_range")


def _validate_element_invariants(document: Document, index: _DocumentIndex) -> None:
    """校验 `element invariants` 相关数据。"""
    element_ids = [element.element_id for element in document.elements]
    _require_unique(element_ids, "element_id 不能重复")
    orders = [element.document_order for element in document.elements]
    if orders != list(range(len(orders))):
        raise ValueError("document_order 必须从 0 连续递增")

    locator_ids = [
        locator.locator_id for element in document.elements for locator in element.locators
    ]
    _require_unique(locator_ids, "locator_id 不能重复")
    enrichment_ids = [
        revision.enrichment_revision_id for revision in document.enrichment_revisions
    ]
    _require_unique(enrichment_ids, "enrichment_revision_id 不能重复")
    enrichment_id_set = set(enrichment_ids)
    if any(
        element.enrichment_revision_id is not None
        and element.enrichment_revision_id not in enrichment_id_set
        for element in document.elements
    ):
        raise ValueError("Element.enrichment_revision_id 引用了不存在的 enrichment")
    if any(
        locator.page_id is not None and locator.page_id not in index.page_ids
        for element in document.elements
        for locator in element.locators
    ):
        raise ValueError("Locator.page_id 引用了不存在的页面")
    for element in document.elements:
        if any(item.artifact_id not in index.asset_ids for item in element.provenance):
            raise ValueError(f"Element.provenance 引用了不存在的资产: {element.element_id}")


def _validate_asset_invariants(document: Document, index: _DocumentIndex) -> None:
    """校验 `asset invariants` 相关数据。"""
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
    if any(
        locator_id not in index.locator_ids
        for asset in document.assets
        for locator_id in asset.locator_ids
    ):
        raise ValueError("Asset.locator_ids 引用了不存在的定位")

    for element in document.elements:
        linked_asset_ids: tuple[str | None, ...] = ()
        if hasattr(element, "asset_id"):
            linked_asset_ids = (element.asset_id,)
        related = element.related_asset_ids
        _require_unique(list(related), f"Element.related_asset_ids 不能重复: {element.element_id}")
        if any(
            asset_id is not None and asset_id not in index.asset_ids
            for asset_id in (*linked_asset_ids, *related)
        ):
            raise ValueError(f"Element.asset_id 引用了不存在的资产: {element.element_id}")


def _validate_section_invariants(document: Document, index: _DocumentIndex) -> None:
    """校验 `section invariants` 相关数据。"""
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
    """校验 `section chain` 相关数据。"""
    seen: set[str] = set()
    cursor = section
    while cursor.parent_section_id is not None:
        if cursor.section_id in seen:
            raise ValueError(f"Section 树存在环: {section.section_id}")
        seen.add(cursor.section_id)
        cursor = index.section_by_id[cursor.parent_section_id]


def _validate_element_relations(document: Document, index: _DocumentIndex) -> None:
    """校验 `element relations` 相关数据。"""
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
    """校验 `element reference` 相关数据。"""
    if reference == owner.element_id:
        raise ValueError(f"Element.{field_name} 不能自引用: {owner.element_id}")
    if reference not in index.element_by_id:
        raise ValueError(f"Element.{field_name} 引用了不存在的元素: {owner.element_id}")


def _validate_parent_chain(element: ElementBase, index: _DocumentIndex) -> None:
    """校验 `parent chain` 相关数据。"""
    seen: set[str] = set()
    cursor = element
    while cursor.parent_element_id is not None:
        if cursor.element_id in seen:
            raise ValueError(f"Element parent 链存在环: {element.element_id}")
        seen.add(cursor.element_id)
        cursor = index.element_by_id[cursor.parent_element_id]


def _validate_quality_invariants(document: Document, index: _DocumentIndex) -> None:
    """校验 `quality invariants` 相关数据。"""
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
