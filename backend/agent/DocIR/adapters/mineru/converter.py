# backend/agent/DocIR/adapters/mineru/converter.py

"""

这个文件干什么：MinerU 3.4.x middle + content_list_v2 → DocIR。

直白点说就是：把 MinerU 的原始 JSON 和资源文件整理成项目内部统一使用的 DocIR 文档。

MinerU 3.4.x middle + content_list_v2 → DocIR。
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any

from ...core.document import (
    Asset,
    Document,
    Page,
    PageRange,
    ParseRevision,
    PrintedPageNumber,
    QualityIssue,
    Section,
    SourceVersion,
    ValidationSummary,
)
from ...core.elements import (
    CodeElement,
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
from ...core.enums import AssetKind, ElementRole, Severity, TextOrigin, ValidationStatus
from ...core.geometry import Locator, SourceGeometry, normalize_bbox
from ...core.text import TextContent, TextLayer
from .alignment import (
    AlignedBlock,
    AlignmentError,
    align_page,
    extract_text,
    types_compatible,
)
from .bundle import MinerUBundle
from .models import RawMiddleBlock, RawMiddlePage


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.pieces: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.pieces.append(value)


def _html_text(value: str) -> str:
    parser = _HTMLText()
    parser.feed(value)
    return " ".join(parser.pieces).strip()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_SOURCE_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def source_media_type(path: Path) -> str:
    """返回源文件 MIME；目标格式使用稳定映射，其他格式保守降级。"""
    source = Path(path)
    return (
        _SOURCE_MEDIA_TYPES.get(source.suffix.lower())
        or mimetypes.guess_type(source.name)[0]
        or "application/octet-stream"
    )


def _stable(prefix: str, *parts: object) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _block_text(block: RawMiddleBlock) -> str:
    return extract_text(block.model_dump(mode="python"))


def _content(item: dict[str, Any] | None) -> dict[str, Any]:
    value = item.get("content") if item else None
    return value if isinstance(value, dict) else {}


def _v2_type(item: dict[str, Any] | None) -> str | None:
    value = item.get("type") if item else None
    return value if isinstance(value, str) else None


def _text_content(element_id: str, value: str, score: float | None) -> TextContent | None:
    if not value:
        return None
    layer_id = f"text_{element_id}"
    return TextContent(
        primary_layer_id=layer_id,
        layers=(
            TextLayer(
                text_layer_id=layer_id,
                origin=TextOrigin.NATIVE_OR_OCR_UNVERIFIED,
                text=value,
                confidence=score,
                quote_eligible=False,
            ),
        ),
    )


def _role(aligned: AlignedBlock) -> ElementRole:
    source_type = _v2_type(aligned.v2) or aligned.middle.type
    if source_type in {"page_header", "header"}:
        return ElementRole.HEADER
    if source_type == "page_footer":
        return ElementRole.FOOTER
    if source_type == "page_number":
        return ElementRole.PAGE_NUMBER
    if aligned.discarded:
        return ElementRole.DISCARDED
    return ElementRole.BODY


def _semantic_text(aligned: AlignedBlock) -> str:
    item = aligned.v2
    block = aligned.middle
    source_type = _v2_type(item) or block.type
    content = _content(item)
    extracted = extract_text(item) if item else _block_text(block)
    if source_type == "table" and not extracted and isinstance(content.get("html"), str):
        return _html_text(content["html"])
    if source_type == "chart":
        caption = extract_text(content.get("chart_caption"))
        structured = content.get("content")
        structured_text = _html_text(structured) if isinstance(structured, str) else ""
        return "\n".join(part for part in (caption, structured_text, extracted) if part).strip()
    if source_type in {"equation_interline", "interline_equation"}:
        math = content.get("math_content")
        if isinstance(math, str) and math.strip():
            return math.strip()
    return extracted or _block_text(block)


def _list_items(content: dict[str, Any]) -> tuple[str, ...]:
    items = content.get("list_items")
    if not isinstance(items, list):
        return ()
    return tuple(text for item in items if (text := extract_text(item)))


def _visual_path(content: dict[str, Any]) -> str | None:
    source = content.get("image_source")
    path = source.get("path") if isinstance(source, dict) else None
    # MinerU 跨页续表占位会产生 ``images/``，它是目录前缀而
    # 不是可解析资产，不应生成 missing-asset 警告。
    return path if isinstance(path, str) and path.strip() and not path.rstrip().endswith("/") else None


def _visual_asset_path(source_path: str, sha256: str) -> str:
    """将 MinerU 相对图片路径映射成稳定、扁平的 DocIR 资产路径。"""
    name = PurePosixPath(source_path).name
    return f"assets/visual/{sha256[:12]}--{name}"


def _is_merged_table_continuation(block: RawMiddleBlock, item: dict[str, Any] | None) -> bool:
    """识别 MinerU 标出的跨页续表占位；不在这里猜测它属于哪张表。"""
    if (_v2_type(item) or block.type) != "table":
        return False
    html = _content(item).get("html")
    if isinstance(html, str) and html.strip():
        return False
    payload = block.model_dump(mode="python")
    bodies = [
        child
        for child in payload.get("blocks", [])
        if isinstance(child, dict) and child.get("type") == "table_body"
    ]
    return bool(bodies) and all(
        body.get("lines_deleted") is True and not body.get("lines")
        for body in bodies
    )


def convert_bundle(
    bundle: MinerUBundle,
    source_file: Path,
    *,
    source_page_count: int | None = None,
    strict: bool = False,
    max_bbox_delta: float = 5.0,
) -> Document:
    """转换一个已加载 bundle；不根据日志猜测 native/OCR 来源。"""
    return _MinerUConverter(
        bundle=bundle,
        source_file=Path(source_file),
        source_page_count=source_page_count,
        strict=strict,
        max_bbox_delta=max_bbox_delta,
    ).convert()


@dataclass
class _ConversionState:
    pages: list[Page] = field(default_factory=list)
    elements: list[ElementBase] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)
    printed_pages: dict[str, PrintedPageNumber] = field(default_factory=dict)
    section_elements: dict[str, list[str]] = field(default_factory=lambda: {"section_root": []})
    sections_meta: dict[str, tuple[str | None, str | None]] = field(
        default_factory=lambda: {"section_root": (None, None)}
    )
    current_section: str = "section_root"
    active_sections_by_level: dict[int, str] = field(default_factory=dict)
    visual_assets: dict[str, str] = field(default_factory=dict)


class _MinerUConverter:
    """持有单次转换状态，并把页面、元素、资产和收尾步骤分开。"""

    def __init__(
        self,
        *,
        bundle: MinerUBundle,
        source_file: Path,
        source_page_count: int | None,
        strict: bool,
        max_bbox_delta: float,
    ) -> None:
        self.bundle = bundle
        self.source_file = source_file
        self.source_page_count = source_page_count
        self.strict = strict
        self.max_bbox_delta = max_bbox_delta
        self.source_hash = file_sha256(source_file)
        self.config = self._conversion_config()
        self.config_hash = hashlib.sha256(
            json.dumps(self.config, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.state = _ConversionState()
        self.original_asset, self.raw_asset_ids = self._register_source_assets()

    def convert(self) -> Document:
        self._validate_page_sets()
        for page_position, raw_page in enumerate(self.bundle.middle.pdf_info):
            self._convert_page(page_position, raw_page)
        return self._build_document()

    def _conversion_config(self) -> dict[str, Any]:
        return {
            "strict": self.strict,
            "source_page_count": self.source_page_count,
            "alignment": "optional_geometry_type_text",
            "max_bbox_delta": self.max_bbox_delta,
            "include_discarded_blocks": True,
            "section_hierarchy": "mineru_explicit_heading_level",
            "table_continuations": "preserve_without_inferred_target",
            "unverified_text_origin": TextOrigin.NATIVE_OR_OCR_UNVERIFIED.value,
        }

    def _register_source_assets(self) -> tuple[Asset, dict[str, str]]:
        original = Asset(
            asset_id="asset_original",
            kind=AssetKind.ORIGINAL,
            path=f"assets/{self.source_file.name}",
            media_type=source_media_type(self.source_file),
            byte_size=self.source_file.stat().st_size,
            sha256=self.source_hash,
        )
        self.state.assets.append(original)
        raw_ids: dict[str, str] = {}
        raw_paths = {
            "middle": self.bundle.middle_path,
            "content_list_v2": self.bundle.content_v2_path,
            "content_list": self.bundle.content_list_path,
            "model": self.bundle.model_path,
        }
        for artifact_name, path in raw_paths.items():
            if path is None:
                continue
            asset_id = _stable("asset", path.name)
            raw_ids[artifact_name] = asset_id
            self.state.assets.append(
                Asset(
                    asset_id=asset_id,
                    kind=AssetKind.RAW_ARTIFACT,
                    path=f"raw/{path.name}",
                    media_type="application/json",
                    byte_size=path.stat().st_size,
                    sha256=file_sha256(path),
                )
            )
        return original, raw_ids

    def _validate_page_sets(self) -> None:
        if not self.bundle.middle.pdf_info:
            raise ValueError("MinerU middle bundle 不包含页面")
        if self.strict and len(self.bundle.content_v2) != len(self.bundle.middle.pdf_info):
            raise AlignmentError(
                f"page count mismatch: middle={len(self.bundle.middle.pdf_info)}, "
                f"v2={len(self.bundle.content_v2)}"
            )

    def _convert_page(self, page_position: int, raw_page: RawMiddlePage) -> None:
        page_id: str | None = None
        width: float | None = None
        height: float | None = None
        if raw_page.page_size is not None:
            if len(raw_page.page_size) != 2:
                raise ValueError("middle page_size 必须是 width/height 二元组")
            width, height = map(float, raw_page.page_size)
            page_id = f"page_{raw_page.page_idx:06d}"
            self.state.pages.append(
                Page(
                    page_id=page_id,
                    page_index=raw_page.page_idx,
                    display_page_no=raw_page.page_idx + 1,
                    width=width,
                    height=height,
                    unit="mineru_middle",
                )
            )
        v2_items = self._v2_page_items(page_position)
        for aligned in align_page(
            raw_page,
            v2_items,
            strict=self.strict,
            max_bbox_delta=self.max_bbox_delta,
        ):
            self._convert_block(
                aligned,
                page_position,
                raw_page.page_idx,
                page_id,
                width,
                height,
            )

    def _v2_page_items(self, page_position: int) -> list[Any]:
        if page_position >= len(self.bundle.content_v2):
            return []
        page_items = self.bundle.content_v2[page_position]
        return page_items if isinstance(page_items, list) else []

    def _convert_block(
        self,
        aligned: AlignedBlock,
        group_index: int,
        page_index: int,
        page_id: str | None,
        width: float | None,
        height: float | None,
    ) -> None:
        block = aligned.middle
        element_id = _stable("element", self.source_hash, page_index, block.index, block.type, block.bbox)
        locator = self._make_locator(
            element_id,
            page_id,
            page_index,
            block,
            width,
            height,
        )
        provenance = self._provenance(aligned, group_index)
        issue_ids = self._alignment_issue_ids(aligned, element_id, page_index)
        if _is_merged_table_continuation(aligned.middle, aligned.v2):
            issue_ids.append(
                self._record_unresolved_table_continuation(element_id, page_index)
            )

        text_value = _semantic_text(aligned)
        text = _text_content(element_id, text_value, block.score)
        if text is not None:
            issue_ids.append(self._record_text_origin_issue(element_id))

        source_type = _v2_type(aligned.v2) or block.type
        visual_asset_id = self._register_visual_asset(
            source_type,
            _content(aligned.v2),
            element_id,
            locator.locator_id,
            issue_ids,
        )
        element = self._create_element(
            aligned,
            element_id,
            locator,
            provenance,
            text,
            source_type,
            visual_asset_id,
            issue_ids,
        )
        self._register_element(
            element,
            text_value,
            block.score,
            page_id,
            locator.locator_id,
        )

    def _make_locator(
        self,
        element_id: str,
        page_id: str | None,
        group_index: int,
        block: RawMiddleBlock,
        width: float | None,
        height: float | None,
    ) -> Locator:
        if page_id is None:
            return Locator(
                locator_id=_stable("locator", element_id, "group", group_index),
                kind="group",
                container_id=f"group_{group_index:06d}",
                container_index=group_index,
                metadata={"source_format": self.source_file.suffix.lower().lstrip(".")},
            )
        if block.bbox is None or width is None or height is None:
            raise ValueError("spatial page block 的 geometry 不完整")
        return Locator(
            locator_id=_stable("locator", element_id, "page", group_index),
            kind="page",
            container_id=page_id,
            container_index=group_index,
            page_id=page_id,
            bbox=normalize_bbox(block.bbox, width, height),
            source_geometry=SourceGeometry(
                coordinate_space="mineru_middle_page",
                bbox=tuple(map(float, block.bbox)),
                page_width=width,
                page_height=height,
            ),
        )

    def _provenance(
        self,
        aligned: AlignedBlock,
        group_index: int,
    ) -> tuple[ElementProvenance, ...]:
        output = [
            ElementProvenance(
                artifact_id=self.raw_asset_ids["middle"],
                json_path=f"$.pdf_info[{group_index}]",
                group_index=group_index,
                block_index=aligned.middle.index,
                source_anchor=("discarded_blocks" if aligned.discarded else "para_blocks"),
            )
        ]
        if aligned.v2_index is not None:
            output.append(
                ElementProvenance(
                    artifact_id=self.raw_asset_ids["content_list_v2"],
                    json_path=f"$[{group_index}][{aligned.v2_index}]",
                    group_index=group_index,
                    block_index=aligned.v2_index,
                )
            )
        return tuple(output)

    def _alignment_issue_ids(self, aligned: AlignedBlock, element_id: str, page_index: int) -> list[str]:
        mismatched = (
            aligned.v2 is None
            or not types_compatible(aligned.middle.type, _v2_type(aligned.v2))
            or (aligned.bbox_delta is not None and aligned.bbox_delta > self.max_bbox_delta)
        )
        if not mismatched:
            return []
        issue = QualityIssue(
            issue_id=_stable("issue", "middle_v2_alignment", element_id),
            code="middle_v2_mismatch",
            severity=Severity.WARNING,
            message=(
                f"page {page_index}: middle={aligned.middle.type}, "
                f"v2={_v2_type(aligned.v2)}, bbox_delta={aligned.bbox_delta}"
            ),
            object_id=element_id,
        )
        self.state.issues.append(issue)
        if self.strict:
            raise AlignmentError(issue.message)
        return [issue.issue_id]

    def _record_unresolved_table_continuation(
        self,
        element_id: str,
        page_index: int,
    ) -> str:
        """保留续表事实，但 MinerU 未给目标 ID 时不连接到“上一张表”。"""
        issue = QualityIssue(
            issue_id=_stable("issue", "table_continuation_target_unavailable", element_id),
            code="table_continuation_target_unavailable",
            severity=Severity.WARNING,
            message=(
                f"page {page_index}: MinerU 标出了跨页续表占位，但没有提供目标表 ID；"
                "DocIR 保留独立元素和 provenance，不推断 owner"
            ),
            object_id=element_id,
        )
        self.state.issues.append(issue)
        return issue.issue_id

    def _record_text_origin_issue(self, element_id: str) -> str:
        issue = QualityIssue(
            issue_id=_stable("issue", "text_origin", element_id),
            code="text_origin_unverified",
            severity=Severity.WARNING,
            message=(
                "MinerU raw 产物未证明该文字来自 native text 还是 OCR；"
                "DocIR 保留 native_or_ocr_unverified 事实，下游按 OCR 风险处理"
            ),
            object_id=element_id,
        )
        self.state.issues.append(issue)
        return issue.issue_id

    def _register_visual_asset(
        self,
        source_type: str,
        content: dict[str, Any],
        element_id: str,
        locator_id: str,
        issue_ids: list[str],
    ) -> str | None:
        visual_path = _visual_path(content)
        if visual_path is None:
            return None
        physical = self.bundle.root / visual_path
        if not physical.is_file():
            issue = QualityIssue(
                issue_id=_stable("issue", "visual_asset", element_id, visual_path),
                code="visual_asset_missing",
                severity=Severity.WARNING,
                message=f"MinerU 视觉资产 {visual_path} 不在 bundle 中",
                object_id=element_id,
            )
            self.state.issues.append(issue)
            issue_ids.append(issue.issue_id)
            return None

        existing = self.state.visual_assets.get(visual_path)
        if existing is not None:
            return existing
        visual_hash = file_sha256(physical)
        asset_id = _stable("asset", "mineru_visual", visual_path, visual_hash)
        self.state.visual_assets[visual_path] = asset_id
        self.state.assets.append(
            Asset(
                asset_id=asset_id,
                kind=AssetKind.TABLE if source_type == "table" else AssetKind.FIGURE,
                path=_visual_asset_path(visual_path, visual_hash),
                media_type=mimetypes.guess_type(physical.name)[0] or "application/octet-stream",
                byte_size=physical.stat().st_size,
                sha256=visual_hash,
                locator_ids=(locator_id,),
            )
        )
        return asset_id

    def _create_element(
        self,
        aligned: AlignedBlock,
        element_id: str,
        locator: Locator,
        provenance: tuple[ElementProvenance, ...],
        text: TextContent | None,
        source_type: str,
        visual_asset_id: str | None,
        issue_ids: list[str],
    ) -> ElementBase:
        content = _content(aligned.v2)
        role = _role(aligned)
        section_id = "section_root" if role != ElementRole.BODY else self.state.current_section
        heading_level: int | None = None
        if source_type == "title":
            heading_level = self._explicit_heading_level(aligned, element_id, issue_ids)
            if heading_level is not None:
                section_id = self._start_section(element_id, heading_level)
        common: dict[str, Any] = {
            "element_id": element_id,
            "document_order": len(self.state.elements),
            "role": role,
            "section_id": section_id,
            "locators": (locator,),
            "provenance": provenance,
            "text": text,
            "quality_issue_ids": tuple(issue_ids),
            "source_type": source_type,
        }
        if source_type == "title":
            return HeadingElement(**common, level=heading_level)
        if source_type in {
            "text",
            "paragraph",
            "abstract",
            "ref_text",
            "page_header",
            "header",
            "page_footer",
            "page_number",
            "page_footnote",
            "page_aside_text",
            "aside_text",
        }:
            return ParagraphElement(**common)
        if source_type in {"list", "index"}:
            attribute = content.get("attribute")
            ordered = True if attribute == "ordered" else False if attribute == "unordered" else None
            return ListElement(**common, ordered=ordered, items=_list_items(content))
        if source_type == "table":
            html = content.get("html")
            return TableElement(
                **common,
                html=html if isinstance(html, str) else None,
                asset_id=visual_asset_id,
                metadata={
                    key: value
                    for key in ("table_type", "table_nest_level")
                    if (value := content.get(key)) is not None
                },
            )
        if source_type in {"equation_interline", "interline_equation"}:
            latex = content.get("math_content")
            return FormulaElement(
                **common,
                latex=latex if isinstance(latex, str) else None,
                asset_id=visual_asset_id,
            )
        if source_type in {"image", "chart"}:
            structured = content.get("content") if source_type == "chart" else None
            return FigureElement(
                **common,
                asset_id=visual_asset_id,
                structured_content=(
                    structured if isinstance(structured, str) and structured.strip() else None
                ),
            )
        if source_type in {"code", "algorithm"}:
            language = content.get("code_language")
            return CodeElement(**common, language=language if isinstance(language, str) and language else None)
        return self._unknown_element(aligned, common, source_type, issue_ids)

    def _explicit_heading_level(
        self,
        aligned: AlignedBlock,
        element_id: str,
        issue_ids: list[str],
    ) -> int | None:
        """只接受 MinerU 明确且一致的 level，不从文字或版面补全。"""

        raw_v2_level = _content(aligned.v2).get("level")
        raw_middle_level = aligned.middle.level
        supplied = [
            value
            for value in (raw_v2_level, raw_middle_level)
            if value is not None
        ]
        valid = [
            value
            for value in supplied
            if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 6
        ]
        if not supplied:
            issue_ids.append(
                self._record_heading_level_issue(
                    element_id,
                    "heading_level_missing",
                    "MinerU 未提供标题 level；DocIR 保留 heading，但不创建推断章节",
                )
            )
            return None
        if len(valid) != len(supplied):
            issue_ids.append(
                self._record_heading_level_issue(
                    element_id,
                    "heading_level_invalid",
                    f"MinerU 标题 level 非法: middle={raw_middle_level!r}, v2={raw_v2_level!r}",
                )
            )
            return None
        if len(set(valid)) != 1:
            issue_ids.append(
                self._record_heading_level_issue(
                    element_id,
                    "heading_level_conflict",
                    f"MinerU 两份产物的标题 level 冲突: middle={raw_middle_level}, v2={raw_v2_level}",
                )
            )
            return None
        return valid[0]

    def _record_heading_level_issue(
        self,
        element_id: str,
        code: str,
        message: str,
    ) -> str:
        issue = QualityIssue(
            issue_id=_stable("issue", code, element_id),
            code=code,
            severity=Severity.WARNING,
            message=message,
            object_id=element_id,
        )
        self.state.issues.append(issue)
        return issue.issue_id

    def _start_section(self, title_element_id: str, level: int) -> str:
        """按 MinerU 的显式 heading level 维护文档顺序中的章节栈。"""

        section_id = _stable("section", title_element_id)
        parent_level = max(
            (candidate for candidate in self.state.active_sections_by_level if candidate < level),
            default=None,
        )
        parent_section_id = (
            self.state.active_sections_by_level[parent_level]
            if parent_level is not None
            else "section_root"
        )
        self.state.sections_meta[section_id] = (parent_section_id, title_element_id)
        self.state.section_elements[section_id] = []
        self.state.active_sections_by_level = {
            candidate: active_section
            for candidate, active_section in self.state.active_sections_by_level.items()
            if candidate < level
        }
        self.state.active_sections_by_level[level] = section_id
        self.state.current_section = section_id
        return section_id

    def _unknown_element(
        self,
        aligned: AlignedBlock,
        common: dict[str, Any],
        source_type: str,
        issue_ids: list[str],
    ) -> UnknownElement:
        issue = QualityIssue(
            issue_id=_stable("issue", "unknown_type", common["element_id"]),
            code="unknown_element_type",
            message=f"未支持的 MinerU 类型: {source_type}",
            object_id=common["element_id"],
        )
        self.state.issues.append(issue)
        if self.strict:
            raise ValueError(issue.message)
        return UnknownElement(
            **{**common, "quality_issue_ids": tuple(issue_ids + [issue.issue_id])},
            raw_type=source_type,
            raw_payload=aligned.v2 or aligned.middle.model_dump(mode="json"),
        )

    def _register_element(
        self,
        element: ElementBase,
        text_value: str,
        confidence: float | None,
        page_id: str | None,
        locator_id: str,
    ) -> None:
        self.state.elements.append(element)
        section_id = element.section_id or "section_root"
        self.state.section_elements.setdefault(section_id, []).append(element.element_id)
        if (
            page_id is not None
            and element.role == ElementRole.PAGE_NUMBER
            and text_value
            and page_id not in self.state.printed_pages
        ):
            self.state.printed_pages[page_id] = PrintedPageNumber(
                text=text_value,
                origin=TextOrigin.NATIVE_OR_OCR_UNVERIFIED,
                confidence=confidence,
                locator_id=locator_id,
            )

    def _build_document(self) -> Document:
        pages = tuple(
            page.model_copy(update={"printed_page": self.state.printed_pages.get(page.page_id)})
            for page in self.state.pages
        )
        sections = tuple(
            Section(
                section_id=section_id,
                parent_section_id=metadata[0],
                title_element_id=metadata[1],
                element_ids=tuple(self.state.section_elements.get(section_id, [])),
            )
            for section_id, metadata in self.state.sections_meta.items()
        )
        page_indexes = [page.page_index for page in pages]
        group_indexes = [page.page_idx for page in self.bundle.middle.pdf_info]
        validation_status = (
            ValidationStatus.PASSED_WITH_WARNINGS if self.state.issues else ValidationStatus.PASSED
        )
        return Document(
            document_id=_stable("doc", self.source_hash),
            created_at=datetime.now(timezone.utc),
            source=SourceVersion(
                source_version_id=f"src_{self.source_hash}",
                filename=self.source_file.name,
                media_type=source_media_type(self.source_file),
                byte_size=self.source_file.stat().st_size,
                sha256=self.source_hash,
                original_asset_id=self.original_asset.asset_id,
            ),
            parse_revision=ParseRevision(
                parse_revision_id=_stable(
                    "parse",
                    self.source_hash,
                    self.bundle.middle.version_name,
                    self.bundle.middle.backend,
                    self.config_hash,
                    min(group_indexes),
                    max(group_indexes),
                ),
                parser_name="MinerU",
                parser_version=self.bundle.middle.version_name or "unknown",
                backend=self.bundle.middle.backend,
                page_range=(
                    PageRange(start=min(page_indexes), end=max(page_indexes))
                    if page_indexes
                    else None
                ),
                config=self.config,
                config_sha256=self.config_hash,
                raw_artifact_ids=tuple(self.raw_asset_ids.values()),
            ),
            source_page_count=self.source_page_count if pages else None,
            parsed_page_count=len(pages),
            pages=pages,
            sections=sections,
            elements=tuple(self.state.elements),
            assets=tuple(self.state.assets),
            quality_issues=tuple(self.state.issues),
            validation=ValidationSummary(
                status=validation_status,
                issue_ids=tuple(issue.issue_id for issue in self.state.issues),
            ),
        )
