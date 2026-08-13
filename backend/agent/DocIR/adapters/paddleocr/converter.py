"""Convert replayable PP-StructureV3 output into parser-neutral DocIR."""

from __future__ import annotations

import hashlib
import json
import math
import mimetypes
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from ...core.document import (
    Asset,
    Document,
    ModelReference,
    Page,
    PageRange,
    ParseRevision,
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
    ParagraphElement,
    TableElement,
    UnknownElement,
)
from ...core.enums import AssetKind, ElementRole, Severity, TextOrigin, ValidationStatus
from ...core.geometry import Locator, SourceGeometry, normalize_bbox
from ...core.text import TextContent, TextLayer
from .bundle import (
    RAW_METADATA_NAME,
    RAW_RESULTS_NAME,
    PaddleOCRBundle,
    page_image_path,
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable(prefix: str, *parts: object) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:24]}"


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.values.append(value)


def _html_text(value: str) -> str:
    parser = _HTMLText()
    parser.feed(value)
    return "\n".join(parser.values)


def _text_content(
    element_id: str,
    value: str,
    confidence: float | None,
) -> TextContent | None:
    if not value.strip():
        return None
    layer_id = f"text_{element_id}"
    return TextContent(
        primary_layer_id=layer_id,
        layers=(
            TextLayer(
                text_layer_id=layer_id,
                origin=TextOrigin.OCR_TEXT,
                text=value,
                confidence=confidence,
                quote_eligible=False,
            ),
        ),
    )


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        return None
    if result[2] <= result[0] or result[3] <= result[1]:
        return None
    return result


def _intersection_over_union(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    x0, y0 = max(left[0], right[0]), max(left[1], right[1])
    x1, y1 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def _average(values: list[float]) -> float | None:
    finite = [value for value in values if math.isfinite(value) and 0 <= value <= 1]
    return sum(finite) / len(finite) if finite else None


def _role(label: str) -> ElementRole:
    return {
        "figure_title": ElementRole.CAPTION,
        "footnote": ElementRole.FOOTNOTE,
        "header": ElementRole.HEADER,
        "footer": ElementRole.FOOTER,
        "number": ElementRole.PAGE_NUMBER,
        "aside_text": ElementRole.ASIDE,
    }.get(label, ElementRole.BODY)


@dataclass(frozen=True)
class ConvertedBundle:
    document: Document
    files: dict[str, bytes]


@dataclass
class _State:
    pages: list[Page] = field(default_factory=list)
    elements: list[ElementBase] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    asset_indexes: dict[str, int] = field(default_factory=dict)
    issues: list[QualityIssue] = field(default_factory=list)
    files: dict[str, bytes] = field(default_factory=dict)
    sections_meta: dict[str, tuple[str | None, str | None]] = field(
        default_factory=lambda: {"section_root": (None, None)}
    )
    section_elements: dict[str, list[str]] = field(
        default_factory=lambda: {"section_root": []}
    )
    current_section: str = "section_root"


class _Converter:
    def __init__(self, bundle: PaddleOCRBundle, source: Path, strict: bool) -> None:
        self.bundle = bundle
        self.source = Path(source).resolve()
        if not self.source.is_file():
            raise FileNotFoundError(self.source)
        self.strict = strict
        self.source_hash = file_sha256(self.source)
        self.state = _State()
        self.raw_results_id = "asset_paddleocr_results"
        self.raw_metadata_id = "asset_paddleocr_metadata"
        self.low_confidence_threshold = float(
            self.bundle.config.get("low_confidence_threshold", 0.5)
        )

    def convert(self) -> ConvertedBundle:
        self._validate_status()
        self._register_fixed_assets()
        for page_position, (raw_page, image) in enumerate(
            zip(self.bundle.pages, self.bundle.page_images, strict=True)
        ):
            self._convert_page(page_position, raw_page, image)
        return ConvertedBundle(self._build_document(), dict(self.state.files))

    def _validate_status(self) -> None:
        if self.bundle.status != "success":
            raise ValueError(
                f"PaddleOCR conversion status 不可消费: {self.bundle.status}"
            )
        if not self.bundle.pages:
            raise ValueError("PaddleOCR bundle 没有页面")

    def _register_fixed_assets(self) -> None:
        original_path = f"assets/{self.source.name}"
        self._add_asset(
            Asset(
                asset_id="asset_original",
                kind=AssetKind.ORIGINAL,
                path=original_path,
                media_type=mimetypes.guess_type(self.source.name)[0]
                or "application/octet-stream",
                byte_size=self.source.stat().st_size,
                sha256=self.source_hash,
            ),
            self.source.read_bytes(),
        )
        for asset_id, name, content in (
            (self.raw_results_id, RAW_RESULTS_NAME, self.bundle.results_bytes),
            (self.raw_metadata_id, RAW_METADATA_NAME, self.bundle.metadata_bytes),
        ):
            path = f"raw/{name}"
            self._add_asset(
                Asset(
                    asset_id=asset_id,
                    kind=AssetKind.RAW_ARTIFACT,
                    path=path,
                    media_type="application/json",
                    byte_size=len(content),
                    sha256=_bytes_sha256(content),
                ),
                content,
            )

    def _add_asset(self, asset: Asset, content: bytes) -> None:
        self.state.asset_indexes[asset.asset_id] = len(self.state.assets)
        self.state.assets.append(asset)
        self.state.files[asset.path] = content

    def _convert_page(
        self,
        page_position: int,
        raw_page: dict[str, Any],
        image_bytes: bytes,
    ) -> None:
        with Image.open(BytesIO(image_bytes)) as loaded:
            image = loaded.convert("RGB")
        width, height = image.size
        raw_width = raw_page.get("width")
        raw_height = raw_page.get("height")
        page_id = f"page_{page_position:06d}"
        page_issues: list[str] = []
        if raw_width != width or raw_height != height:
            issue = self._issue(
                "paddleocr_page_dimension_mismatch",
                f"page {page_position}: raw={raw_width}x{raw_height}, image={width}x{height}",
                page_id,
            )
            page_issues.append(issue)
            if self.strict:
                raise ValueError(self.state.issues[-1].message)
        raw_index = raw_page.get("page_index")
        if raw_index is not None and raw_index != page_position:
            issue = self._issue(
                "paddleocr_page_index_mismatch",
                f"page position={page_position}, PaddleOCR page_index={raw_index}",
                page_id,
            )
            page_issues.append(issue)
            if self.strict:
                raise ValueError(self.state.issues[-1].message)

        page_path = page_image_path(page_position)
        page_asset_id = _stable(
            "asset", "page", page_position, _bytes_sha256(image_bytes)
        )
        self._add_asset(
            Asset(
                asset_id=page_asset_id,
                kind=AssetKind.PAGE_IMAGE,
                path=page_path,
                media_type="image/png",
                byte_size=len(image_bytes),
                sha256=_bytes_sha256(image_bytes),
            ),
            image_bytes,
        )
        self.state.pages.append(
            Page(
                page_id=page_id,
                page_index=page_position,
                display_page_no=page_position + 1,
                width=width,
                height=height,
                unit="px",
                page_image_asset_id=page_asset_id,
                quality_issue_ids=tuple(page_issues),
            )
        )

        blocks = raw_page.get("parsing_res_list")
        if not isinstance(blocks, list):
            raise TypeError(f"page {page_position} parsing_res_list 不是数组")
        table_index = 0
        for block_position, block in enumerate(blocks):
            if not isinstance(block, dict):
                raise TypeError("PaddleOCR parsing block 不是对象")
            self._convert_block(
                page_position,
                block_position,
                block,
                raw_page,
                image,
                table_index,
            )
            if str(block.get("block_label")) == "table":
                table_index += 1

    def _convert_block(
        self,
        page_index: int,
        block_position: int,
        block: dict[str, Any],
        raw_page: dict[str, Any],
        image: Image.Image,
        table_index: int,
    ) -> None:
        label = str(block.get("block_label") or "unknown")
        element_id = _stable(
            "element",
            self.source_hash,
            page_index,
            block_position,
            block.get("block_id"),
        )
        issues: list[str] = []
        raw_bbox = _bbox(block.get("block_bbox"))
        locator: Locator | None = None
        if raw_bbox is None:
            issues.append(
                self._issue(
                    "paddleocr_block_bbox_missing",
                    f"page {page_index} block {block_position} 缺少有效 bbox",
                    element_id,
                )
            )
            if self.strict:
                raise ValueError(self.state.issues[-1].message)
        else:
            locator = Locator(
                locator_id=_stable("locator", element_id, page_index, block_position),
                kind="page",
                container_id=f"page_{page_index:06d}",
                container_index=page_index,
                page_id=f"page_{page_index:06d}",
                bbox=normalize_bbox(raw_bbox, image.width, image.height),
                source_geometry=SourceGeometry(
                    coordinate_space="paddleocr_top_left_pixels",
                    bbox=raw_bbox,
                    page_width=image.width,
                    page_height=image.height,
                ),
            )
        confidence = self._ocr_confidence(raw_page, raw_bbox, label, table_index)
        layout_score = self._layout_score(raw_page, raw_bbox, label)
        if confidence is not None and confidence < self.low_confidence_threshold:
            issues.append(
                self._issue(
                    "paddleocr_low_text_confidence",
                    f"OCR confidence={confidence:.4f} 低于 {self.low_confidence_threshold}",
                    element_id,
                )
            )
        content = block.get("block_content")
        text = content if isinstance(content, str) else ""
        role = _role(label)
        common: dict[str, Any] = {
            "element_id": element_id,
            "document_order": len(self.state.elements),
            "role": role,
            "section_id": (
                "section_root"
                if role != ElementRole.BODY
                else self.state.current_section
            ),
            "locators": (locator,) if locator is not None else (),
            "provenance": (
                ElementProvenance(
                    artifact_id=self.raw_results_id,
                    json_path=(
                        f"$.pages[{page_index}].parsing_res_list[{block_position}]"
                    ),
                    group_index=page_index,
                    block_index=block_position,
                    source_anchor=str(block.get("block_id")),
                ),
            ),
            "text": _text_content(element_id, text, confidence),
            "quality_issue_ids": tuple(issues),
            "source_type": label,
            "metadata": {
                "paddleocr_block_id": block.get("block_id"),
                "paddleocr_block_order": block.get("block_order"),
                "layout_score": layout_score,
            },
        }
        if label == "doc_title":
            common["section_id"] = self._start_section(element_id)
            element: ElementBase = HeadingElement(**common, level=1)
        elif label == "paragraph_title":
            issue_id = self._issue(
                "paddleocr_heading_level_missing",
                "PP-StructureV3 标记了 paragraph_title，但没有提供标题级别",
                element_id,
            )
            common["quality_issue_ids"] = tuple([*issues, issue_id])
            element = HeadingElement(**common, level=None)
        elif label == "table":
            html = text or self._table_html(raw_page, table_index)
            common["text"] = _text_content(element_id, _html_text(html), confidence)
            element = TableElement(
                **common,
                html=html or None,
                asset_id=self._visual_asset(
                    image, raw_bbox, element_id, locator, AssetKind.TABLE
                ),
            )
        elif label == "formula":
            element = FormulaElement(
                **common,
                latex=text or None,
                asset_id=self._visual_asset(
                    image, raw_bbox, element_id, locator, AssetKind.FIGURE
                ),
            )
        elif label in {"image", "chart", "seal"}:
            common["text"] = None
            element = FigureElement(
                **common,
                asset_id=self._visual_asset(
                    image, raw_bbox, element_id, locator, AssetKind.FIGURE
                ),
                structured_content=text or None if label == "chart" else None,
            )
        elif label == "algorithm":
            element = CodeElement(**common)
        elif label in {
            "text",
            "abstract",
            "content",
            "figure_title",
            "formula_number",
            "reference",
            "reference_content",
            "footnote",
            "header",
            "footer",
            "number",
            "aside_text",
        }:
            element = ParagraphElement(**common)
        else:
            issue_id = self._issue(
                "unknown_paddleocr_label",
                f"未支持的 PP-StructureV3 block_label: {label}",
                element_id,
            )
            if self.strict:
                raise ValueError(self.state.issues[-1].message)
            common["quality_issue_ids"] = tuple([*issues, issue_id])
            element = UnknownElement(**common, raw_type=label, raw_payload=block)
        self._register(element)

    def _layout_score(
        self,
        page: dict[str, Any],
        block_bbox: tuple[float, float, float, float] | None,
        label: str,
    ) -> float | None:
        if block_bbox is None:
            return None
        layout = page.get("layout_det_res")
        boxes = layout.get("boxes") if isinstance(layout, dict) else None
        candidates: list[tuple[float, float]] = []
        if isinstance(boxes, list):
            for item in boxes:
                if not isinstance(item, dict) or str(item.get("label")) != label:
                    continue
                candidate_bbox = _bbox(item.get("coordinate"))
                score = item.get("score")
                if candidate_bbox is not None and isinstance(score, (int, float)):
                    candidates.append(
                        (
                            _intersection_over_union(block_bbox, candidate_bbox),
                            float(score),
                        )
                    )
        return max(candidates, default=(0.0, None), key=lambda item: item[0])[1]

    def _ocr_confidence(
        self,
        page: dict[str, Any],
        block_bbox: tuple[float, float, float, float] | None,
        label: str,
        table_index: int,
    ) -> float | None:
        if label == "table":
            tables = page.get("table_res_list")
            if isinstance(tables, list) and table_index < len(tables):
                table = tables[table_index]
                ocr = table.get("table_ocr_pred") if isinstance(table, dict) else None
                scores = ocr.get("rec_scores") if isinstance(ocr, dict) else None
                if isinstance(scores, list):
                    return _average([float(value) for value in scores])
        if block_bbox is None:
            return None
        ocr = page.get("overall_ocr_res")
        boxes = ocr.get("rec_boxes") if isinstance(ocr, dict) else None
        scores = ocr.get("rec_scores") if isinstance(ocr, dict) else None
        selected: list[float] = []
        if isinstance(boxes, list) and isinstance(scores, list):
            for raw_box, score in zip(boxes, scores, strict=False):
                candidate = _bbox(raw_box)
                if candidate is None or not isinstance(score, (int, float)):
                    continue
                center_x = (candidate[0] + candidate[2]) / 2
                center_y = (candidate[1] + candidate[3]) / 2
                if (
                    block_bbox[0] <= center_x <= block_bbox[2]
                    and block_bbox[1] <= center_y <= block_bbox[3]
                ):
                    selected.append(float(score))
        return _average(selected)

    @staticmethod
    def _table_html(page: dict[str, Any], table_index: int) -> str:
        tables = page.get("table_res_list")
        if not isinstance(tables, list) or table_index >= len(tables):
            return ""
        table = tables[table_index]
        value = table.get("pred_html") if isinstance(table, dict) else None
        return value if isinstance(value, str) else ""

    def _visual_asset(
        self,
        page_image: Image.Image,
        bbox: tuple[float, float, float, float] | None,
        element_id: str,
        locator: Locator | None,
        kind: AssetKind,
    ) -> str | None:
        if bbox is None:
            return None
        crop_box = (
            max(0, math.floor(bbox[0])),
            max(0, math.floor(bbox[1])),
            min(page_image.width, math.ceil(bbox[2])),
            min(page_image.height, math.ceil(bbox[3])),
        )
        if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
            return None
        stream = BytesIO()
        page_image.crop(crop_box).save(stream, format="PNG", optimize=False)
        content = stream.getvalue()
        digest = _bytes_sha256(content)
        asset_id = _stable("asset", "paddleocr_visual", kind.value, digest)
        locator_ids = (locator.locator_id,) if locator is not None else ()
        if asset_id in self.state.asset_indexes:
            index = self.state.asset_indexes[asset_id]
            existing = self.state.assets[index]
            merged = tuple(dict.fromkeys((*existing.locator_ids, *locator_ids)))
            self.state.assets[index] = existing.model_copy(
                update={"locator_ids": merged}
            )
            return asset_id
        path = f"assets/visual/{digest[:12]}--{kind.value}.png"
        self._add_asset(
            Asset(
                asset_id=asset_id,
                kind=kind,
                path=path,
                media_type="image/png",
                byte_size=len(content),
                sha256=digest,
                locator_ids=locator_ids,
            ),
            content,
        )
        return asset_id

    def _issue(self, code: str, message: str, object_id: str | None) -> str:
        issue = QualityIssue(
            issue_id=_stable("issue", code, object_id, message),
            code=code,
            severity=Severity.WARNING,
            message=message,
            object_id=object_id,
        )
        self.state.issues.append(issue)
        return issue.issue_id

    def _start_section(self, title_element_id: str) -> str:
        section_id = _stable("section", title_element_id)
        self.state.sections_meta[section_id] = ("section_root", title_element_id)
        self.state.section_elements[section_id] = []
        self.state.current_section = section_id
        return section_id

    def _register(self, element: ElementBase) -> None:
        self.state.elements.append(element)
        self.state.section_elements.setdefault(
            element.section_id or "section_root", []
        ).append(element.element_id)

    def _build_document(self) -> Document:
        config_bytes = json.dumps(
            self.bundle.config, sort_keys=True, separators=(",", ":")
        ).encode()
        config_hash = _bytes_sha256(config_bytes)
        parser_version = str(self.bundle.version.get("paddleocr") or "unknown")
        model_fields = sorted(
            (key, value)
            for key, value in self.bundle.config.items()
            if key.endswith("_model_name") and isinstance(value, str)
        )
        page_count_values = [
            value
            for page in self.bundle.pages
            if isinstance((value := page.get("page_count")), int)
        ]
        source_page_count = (
            max(page_count_values) if page_count_values else len(self.state.pages)
        )
        sections = tuple(
            Section(
                section_id=section_id,
                parent_section_id=metadata[0],
                title_element_id=metadata[1],
                element_ids=tuple(self.state.section_elements.get(section_id, ())),
            )
            for section_id, metadata in self.state.sections_meta.items()
        )
        title = next(
            (
                layer.text
                for element in self.state.elements
                if element.source_type == "doc_title" and element.text is not None
                for layer in element.text.layers
                if layer.text_layer_id == element.text.primary_layer_id
            ),
            None,
        )
        return Document(
            document_id=_stable("doc", self.source_hash),
            created_at=datetime.now(timezone.utc),
            source=SourceVersion(
                source_version_id=f"src_{self.source_hash}",
                filename=self.source.name,
                media_type=mimetypes.guess_type(self.source.name)[0]
                or "application/octet-stream",
                byte_size=self.source.stat().st_size,
                sha256=self.source_hash,
                original_asset_id="asset_original",
            ),
            parse_revision=ParseRevision(
                parse_revision_id=_stable(
                    "parse", self.source_hash, parser_version, config_hash
                ),
                parser_name="PaddleOCR",
                parser_version=parser_version,
                backend="PP-StructureV3",
                method="local_gpu",
                page_range=PageRange(start=0, end=len(self.state.pages) - 1),
                config=self.bundle.config,
                config_sha256=config_hash,
                models=tuple(ModelReference(name=value) for _, value in model_fields),
                raw_artifact_ids=(self.raw_results_id, self.raw_metadata_id),
            ),
            title=title,
            source_page_count=source_page_count,
            parsed_page_count=len(self.state.pages),
            pages=tuple(self.state.pages),
            sections=sections,
            elements=tuple(self.state.elements),
            assets=tuple(self.state.assets),
            quality_issues=tuple(self.state.issues),
            validation=ValidationSummary(
                status=(
                    ValidationStatus.PASSED_WITH_WARNINGS
                    if self.state.issues
                    else ValidationStatus.PASSED
                ),
                issue_ids=tuple(issue.issue_id for issue in self.state.issues),
            ),
        )


def build_converted_bundle(
    bundle: PaddleOCRBundle,
    source: Path,
    *,
    strict: bool = False,
) -> ConvertedBundle:
    return _Converter(bundle, source, strict).convert()


def convert_bundle(
    bundle: PaddleOCRBundle,
    source: Path,
    *,
    strict: bool = False,
) -> Document:
    return build_converted_bundle(bundle, source, strict=strict).document
