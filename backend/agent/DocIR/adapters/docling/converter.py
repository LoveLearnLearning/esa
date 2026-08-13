"""Convert DoclingDocument into the repository's parser-neutral DocIR."""

from __future__ import annotations

import hashlib
import json
import mimetypes
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

from docling_core.types.doc import (
    CodeItem,
    ContentLayer,
    DocItemLabel,
    FormulaItem,
    ListItem,
    PictureItem,
    SectionHeaderItem,
    TableItem,
    TitleItem,
)

from ...core.document import (
    Asset,
    Document,
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
    ListElement,
    ParagraphElement,
    TableElement,
    UnknownElement,
)
from ...core.enums import AssetKind, ElementRole, Severity, TextOrigin, ValidationStatus
from ...core.geometry import Locator, SourceGeometry, normalize_bbox
from ...core.text import TextContent, TextLayer
from .bundle import RAW_DOCUMENT_NAME, RAW_METADATA_NAME, DoclingBundle


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


def _media_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _png_bytes(image: Any) -> bytes:
    stream = BytesIO()
    image.convert("RGB").save(stream, format="PNG", optimize=False)
    return stream.getvalue()


def _label(item: Any) -> str:
    value = getattr(item, "label", None)
    return getattr(value, "value", str(value or type(item).__name__))


def _text(item: Any) -> str:
    value = getattr(item, "text", None)
    return value if isinstance(value, str) else ""


def _text_content(element_id: str, value: str) -> TextContent | None:
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
                quote_eligible=False,
            ),
        ),
    )


def _role(item: Any) -> ElementRole:
    label = _label(item)
    if label == DocItemLabel.CAPTION.value:
        return ElementRole.CAPTION
    if label == DocItemLabel.FOOTNOTE.value:
        return ElementRole.FOOTNOTE
    if label == DocItemLabel.PAGE_HEADER.value:
        return ElementRole.HEADER
    if label == DocItemLabel.PAGE_FOOTER.value:
        return ElementRole.FOOTER
    layer = getattr(item, "content_layer", ContentLayer.BODY)
    if layer == ContentLayer.NOTES:
        return ElementRole.ASIDE
    if layer in {ContentLayer.BACKGROUND, ContentLayer.INVISIBLE}:
        return ElementRole.DISCARDED
    return ElementRole.BODY


@dataclass(frozen=True)
class ConvertedBundle:
    document: Document
    files: dict[str, bytes]


@dataclass
class _State:
    pages: list[Page] = field(default_factory=list)
    elements: list[ElementBase] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)
    files: dict[str, bytes] = field(default_factory=dict)
    ref_to_element: dict[str, str] = field(default_factory=dict)
    pending_relations: dict[str, dict[str, tuple[str, ...] | str | None]] = field(
        default_factory=dict
    )
    section_elements: dict[str, list[str]] = field(
        default_factory=lambda: {"section_root": []}
    )
    sections_meta: dict[str, tuple[str | None, str | None]] = field(
        default_factory=lambda: {"section_root": (None, None)}
    )
    active_sections: dict[int, str] = field(default_factory=dict)
    current_section: str = "section_root"


class _Converter:
    def __init__(self, bundle: DoclingBundle, source: Path, strict: bool) -> None:
        self.bundle = bundle
        self.source = Path(source).resolve()
        if not self.source.is_file():
            raise FileNotFoundError(self.source)
        self.strict = strict
        self.source_hash = file_sha256(self.source)
        self.state = _State()
        self.raw_document_id = "asset_docling_document"
        self.raw_metadata_id = "asset_docling_metadata"

    def convert(self) -> ConvertedBundle:
        self._validate_status()
        self._register_fixed_assets()
        self._register_pages()
        self._convert_items()
        self._resolve_relations()
        return ConvertedBundle(self._build_document(), dict(self.state.files))

    def _validate_status(self) -> None:
        if self.bundle.status == "failure":
            raise ValueError("Docling conversion status=failure，不能构造 DocIR")
        if self.bundle.status == "partial_success":
            if self.strict:
                raise ValueError("strict 模式拒绝 Docling partial_success")
            self.state.issues.append(
                QualityIssue(
                    issue_id="issue_docling_partial_success",
                    code="docling_partial_success",
                    severity=Severity.WARNING,
                    message=f"Docling 部分成功并报告 {len(self.bundle.errors)} 个错误",
                )
            )
        elif self.bundle.status != "success":
            raise ValueError(f"Docling conversion status 不可消费: {self.bundle.status}")

    def _register_fixed_assets(self) -> None:
        original_path = f"assets/{self.source.name}"
        self.state.assets.append(
            Asset(
                asset_id="asset_original",
                kind=AssetKind.ORIGINAL,
                path=original_path,
                media_type=_media_type(self.source),
                byte_size=self.source.stat().st_size,
                sha256=self.source_hash,
            )
        )
        self.state.files[original_path] = self.source.read_bytes()
        raw = {
            self.raw_document_id: (f"raw/{RAW_DOCUMENT_NAME}", self.bundle.document_bytes),
            self.raw_metadata_id: (f"raw/{RAW_METADATA_NAME}", self.bundle.metadata_bytes),
        }
        for asset_id, (path, content) in raw.items():
            self.state.files[path] = content
            self.state.assets.append(
                Asset(
                    asset_id=asset_id,
                    kind=AssetKind.RAW_ARTIFACT,
                    path=path,
                    media_type="application/json",
                    byte_size=len(content),
                    sha256=_bytes_sha256(content),
                )
            )

    def _register_pages(self) -> None:
        for page_no, raw_page in sorted(self.bundle.document.pages.items()):
            page_id = f"page_{page_no - 1:06d}"
            image_asset_id = None
            if raw_page.image is not None:
                content = _png_bytes(raw_page.image.pil_image)
                digest = _bytes_sha256(content)
                path = f"assets/pages/{digest[:12]}--page-{page_no}.png"
                image_asset_id = _stable("asset", "page", page_no, digest)
                self.state.files[path] = content
                self.state.assets.append(
                    Asset(
                        asset_id=image_asset_id,
                        kind=AssetKind.PAGE_IMAGE,
                        path=path,
                        media_type="image/png",
                        byte_size=len(content),
                        sha256=digest,
                    )
                )
            self.state.pages.append(
                Page(
                    page_id=page_id,
                    page_index=page_no - 1,
                    display_page_no=page_no,
                    width=raw_page.size.width,
                    height=raw_page.size.height,
                    unit="pt",
                    page_image_asset_id=image_asset_id,
                )
            )

    def _content_items(self) -> Iterable[Any]:
        for item, _level in self.bundle.document.iterate_items(with_groups=False):
            yield item

    def _convert_items(self) -> None:
        items = list(self._content_items())
        index = 0
        while index < len(items):
            item = items[index]
            if isinstance(item, ListItem):
                group = [item]
                parent = getattr(getattr(item, "parent", None), "cref", None)
                index += 1
                while index < len(items) and isinstance(items[index], ListItem):
                    candidate = items[index]
                    candidate_parent = getattr(
                        getattr(candidate, "parent", None), "cref", None
                    )
                    if candidate_parent != parent:
                        break
                    group.append(candidate)
                    index += 1
                self._convert_list(group)
                continue
            self._convert_item(item)
            index += 1

    def _base(self, item: Any, element_id: str) -> dict[str, Any]:
        locators = self._locators(item, element_id)
        role = _role(item)
        section_id = "section_root" if role != ElementRole.BODY else self.state.current_section
        common = {
            "element_id": element_id,
            "document_order": len(self.state.elements),
            "role": role,
            "section_id": section_id,
            "locators": locators,
            "provenance": (
                ElementProvenance(
                    artifact_id=self.raw_document_id,
                    json_path=item.self_ref,
                    source_anchor=item.self_ref,
                ),
            ),
            "text": _text_content(element_id, _text(item)),
            "source_type": _label(item),
            "metadata": {
                "docling_self_ref": item.self_ref,
                "content_layer": getattr(
                    getattr(item, "content_layer", None), "value", "body"
                ),
            },
        }
        self._remember_relations(item, element_id)
        return common

    def _locators(self, item: Any, element_id: str) -> tuple[Locator, ...]:
        output = []
        for index, prov in enumerate(getattr(item, "prov", ())):
            page = self.bundle.document.pages.get(prov.page_no)
            if page is None:
                issue_id = _stable("issue", "missing_page", element_id, prov.page_no)
                self.state.issues.append(
                    QualityIssue(
                        issue_id=issue_id,
                        code="docling_provenance_page_missing",
                        message=f"Docling provenance 引用了不存在的 page_no={prov.page_no}",
                        object_id=element_id,
                    )
                )
                if self.strict:
                    raise ValueError(self.state.issues[-1].message)
                continue
            top_left = prov.bbox.to_top_left_origin(page.size.height)
            raw = top_left.as_tuple()
            output.append(
                Locator(
                    locator_id=_stable("locator", element_id, index, prov.page_no),
                    kind="page",
                    container_id=f"page_{prov.page_no - 1:06d}",
                    container_index=prov.page_no - 1,
                    page_id=f"page_{prov.page_no - 1:06d}",
                    bbox=normalize_bbox(raw, page.size.width, page.size.height),
                    source_geometry=SourceGeometry(
                        coordinate_space="docling_top_left_points",
                        bbox=tuple(float(value) for value in raw),
                        page_width=page.size.width,
                        page_height=page.size.height,
                    ),
                    metadata={
                        "docling_page_no": prov.page_no,
                        "docling_coord_origin": prov.bbox.coord_origin.value,
                        "docling_bbox": list(prov.bbox.as_tuple()),
                        "charspan": list(prov.charspan),
                    },
                )
            )
        return tuple(output)

    def _convert_item(self, item: Any) -> None:
        element_id = _stable("element", self.source_hash, item.self_ref)
        common = self._base(item, element_id)
        if isinstance(item, TitleItem):
            level = 1
            common["section_id"] = self._start_section(element_id, level)
            element: ElementBase = HeadingElement(**common, level=level)
        elif isinstance(item, SectionHeaderItem):
            level = item.level if 1 <= item.level <= 6 else None
            if level is None:
                issue = QualityIssue(
                    issue_id=_stable("issue", "heading_level", element_id),
                    code="docling_heading_level_out_of_range",
                    message=f"Docling heading level={item.level} 超出 DocIR 1..6",
                    object_id=element_id,
                )
                self.state.issues.append(issue)
                common["quality_issue_ids"] = (issue.issue_id,)
            else:
                common["section_id"] = self._start_section(element_id, level)
            element = HeadingElement(**common, level=level)
        elif isinstance(item, TableItem):
            asset_id = self._visual_asset(item, element_id, AssetKind.TABLE, common["locators"])
            html = item.export_to_html(doc=self.bundle.document, add_caption=False)
            text = item.export_to_markdown(doc=self.bundle.document)
            common["text"] = _text_content(element_id, text)
            element = TableElement(**common, html=html, asset_id=asset_id)
        elif isinstance(item, PictureItem):
            asset_id = self._visual_asset(item, element_id, AssetKind.FIGURE, common["locators"])
            element = FigureElement(**common, asset_id=asset_id)
        elif isinstance(item, FormulaItem):
            element = FormulaElement(**common, latex=item.text)
        elif isinstance(item, CodeItem):
            language = getattr(getattr(item, "code_language", None), "value", None)
            element = CodeElement(**common, language=language if language != "unknown" else None)
        elif hasattr(item, "text"):
            element = ParagraphElement(**common)
        else:
            element = self._unknown(item, common)
        self._register(element)

    def _convert_list(self, items: list[ListItem]) -> None:
        refs = tuple(item.self_ref for item in items)
        element_id = _stable("element", self.source_hash, "list", refs)
        common = self._base(items[0], element_id)
        locators = []
        provenance = []
        for item in items:
            locators.extend(self._locators(item, element_id))
            provenance.append(
                ElementProvenance(
                    artifact_id=self.raw_document_id,
                    json_path=item.self_ref,
                    source_anchor=item.self_ref,
                )
            )
            self.state.ref_to_element[item.self_ref] = element_id
        common["locators"] = tuple(
            locator.model_copy(
                update={
                    "locator_id": _stable(
                        "locator", element_id, index, locator.metadata["docling_page_no"]
                    )
                }
            )
            for index, locator in enumerate(locators)
        )
        common["provenance"] = tuple(provenance)
        values = tuple(item.text for item in items if item.text)
        common["text"] = _text_content(element_id, "\n".join(values))
        ordered_values = {item.enumerated for item in items}
        ordered = ordered_values.pop() if len(ordered_values) == 1 else None
        element = ListElement(**common, ordered=ordered, items=values)
        self._register(element)

    def _visual_asset(
        self,
        item: Any,
        element_id: str,
        kind: AssetKind,
        locators: tuple[Locator, ...],
    ) -> str | None:
        image = item.get_image(self.bundle.document)
        if image is None:
            return None
        content = _png_bytes(image)
        digest = _bytes_sha256(content)
        path = f"assets/visual/{digest[:12]}--{kind.value}.png"
        asset_id = _stable("asset", "docling_visual", digest)
        self.state.files.setdefault(path, content)
        if not any(asset.asset_id == asset_id for asset in self.state.assets):
            self.state.assets.append(
                Asset(
                    asset_id=asset_id,
                    kind=kind,
                    path=path,
                    media_type="image/png",
                    byte_size=len(content),
                    sha256=digest,
                    locator_ids=tuple(locator.locator_id for locator in locators),
                )
            )
        return asset_id

    def _unknown(self, item: Any, common: dict[str, Any]) -> UnknownElement:
        issue = QualityIssue(
            issue_id=_stable("issue", "unknown", common["element_id"]),
            code="unknown_docling_item",
            message=f"未显式支持的 Docling item: {type(item).__name__}/{_label(item)}",
            object_id=common["element_id"],
        )
        self.state.issues.append(issue)
        if self.strict:
            raise ValueError(issue.message)
        return UnknownElement(
            **{**common, "quality_issue_ids": (issue.issue_id,)},
            raw_type=_label(item),
            raw_payload=item.model_dump(mode="json", by_alias=True),
        )

    def _remember_relations(self, item: Any, element_id: str) -> None:
        self.state.ref_to_element[item.self_ref] = element_id

        def refs(name: str) -> tuple[str, ...]:
            return tuple(ref.cref for ref in getattr(item, name, ()))

        parent = getattr(getattr(item, "parent", None), "cref", None)
        self.state.pending_relations[element_id] = {
            "parent": parent,
            "captions": refs("captions"),
            "footnotes": refs("footnotes"),
        }

    def _resolve_relations(self) -> None:
        for index, element in enumerate(self.state.elements):
            relations = self.state.pending_relations.get(element.element_id, {})

            def resolve(value: str | None) -> str | None:
                return self.state.ref_to_element.get(value) if value else None

            parent = resolve(relations.get("parent"))
            captions = tuple(
                result
                for value in relations.get("captions", ())
                if (result := resolve(value)) is not None and result != element.element_id
            )
            footnotes = tuple(
                result
                for value in relations.get("footnotes", ())
                if (result := resolve(value)) is not None and result != element.element_id
            )
            if parent == element.element_id:
                parent = None
            self.state.elements[index] = element.model_copy(
                update={
                    "parent_element_id": parent,
                    "caption_element_ids": tuple(dict.fromkeys(captions)),
                    "footnote_element_ids": tuple(dict.fromkeys(footnotes)),
                }
            )

    def _start_section(self, title_element_id: str, level: int) -> str:
        section_id = _stable("section", title_element_id)
        parent_level = max((value for value in self.state.active_sections if value < level), default=None)
        parent_id = self.state.active_sections[parent_level] if parent_level else "section_root"
        self.state.sections_meta[section_id] = (parent_id, title_element_id)
        self.state.section_elements[section_id] = []
        self.state.active_sections = {
            value: section
            for value, section in self.state.active_sections.items()
            if value < level
        }
        self.state.active_sections[level] = section_id
        self.state.current_section = section_id
        return section_id

    def _register(self, element: ElementBase) -> None:
        self.state.elements.append(element)
        self.state.section_elements.setdefault(
            element.section_id or "section_root", []
        ).append(element.element_id)

    def _build_document(self) -> Document:
        sections = tuple(
            Section(
                section_id=section_id,
                parent_section_id=metadata[0],
                title_element_id=metadata[1],
                element_ids=tuple(self.state.section_elements.get(section_id, ())),
            )
            for section_id, metadata in self.state.sections_meta.items()
        )
        page_indexes = [page.page_index for page in self.state.pages]
        config_hash = _bytes_sha256(
            json.dumps(
                self.bundle.config, sort_keys=True, separators=(",", ":")
            ).encode()
        )
        parser_version = str(
            self.bundle.version.get("docling_version")
            or self.bundle.version.get("docling")
            or "unknown"
        )
        return Document(
            document_id=_stable("doc", self.source_hash),
            created_at=datetime.now(timezone.utc),
            source=SourceVersion(
                source_version_id=f"src_{self.source_hash}",
                filename=self.source.name,
                media_type=_media_type(self.source),
                byte_size=self.source.stat().st_size,
                sha256=self.source_hash,
                original_asset_id="asset_original",
            ),
            parse_revision=ParseRevision(
                parse_revision_id=_stable(
                    "parse", self.source_hash, parser_version, config_hash
                ),
                parser_name="Docling",
                parser_version=parser_version,
                backend="standard",
                method="local_cuda",
                page_range=(
                    PageRange(start=min(page_indexes), end=max(page_indexes))
                    if page_indexes
                    else None
                ),
                config=self.bundle.config,
                config_sha256=config_hash,
                raw_artifact_ids=(self.raw_document_id, self.raw_metadata_id),
            ),
            title=next(
                (
                    _text(element)
                    for element in self.bundle.document.texts
                    if isinstance(element, TitleItem) and _text(element)
                ),
                None,
            ),
            source_page_count=len(self.state.pages) or None,
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
    bundle: DoclingBundle,
    source: Path,
    *,
    strict: bool = False,
) -> ConvertedBundle:
    return _Converter(bundle, source, strict).convert()


def convert_bundle(
    bundle: DoclingBundle,
    source: Path,
    *,
    strict: bool = False,
) -> Document:
    """Convert an existing Docling result without rerunning the parser."""

    return build_converted_bundle(bundle, source, strict=strict).document
