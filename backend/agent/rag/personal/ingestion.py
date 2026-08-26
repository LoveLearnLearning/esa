"""DocIR and Chunk ingestion dedicated to durable personal knowledge bases."""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.agent.DocIR.core import (
    Asset,
    AssetKind,
    Document,
    ElementRole,
    HeadingElement,
    Locator,
    ParagraphElement,
    ParseRevision,
    Section,
    SourceVersion,
    TextContent,
    TextLayer,
    TextOrigin,
    ValidationStatus,
    ValidationSummary,
)
from backend.agent.DocIR.io import load_document, save_document
from backend.agent.mm.contracts import DocumentParser
from backend.agent.rag.chunk import ChunkBuilder, ChunkConfig, ChunkDocument
from backend.agent.rag.chunk.serializer import file_sha256, load_chunk_document, save_json
from backend.agent.rag.fingerprints import configuration_sha256
from .preview import LibreOfficePreviewConverter


LOCATOR_SCHEMA_VERSION = "personal-locator-0.1"
NATIVE_PARSER_VERSION = "personal-native-0.1"
NATIVE_SUFFIXES = frozenset({".txt", ".md", ".csv", ".json"})
MINERU_SUFFIXES = frozenset(
    {
        ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
        ".png", ".jpg", ".jpeg", ".webp",
    }
)

logger = logging.getLogger(__name__)
_PREVIEW_TEXT_MAX_BYTES = 512 * 1024
_OFFICE_SUFFIXES = frozenset({".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"})


@dataclass(frozen=True, slots=True)
class PersonalIngestionResult:
    document: Document
    chunks: ChunkDocument
    artifact_root: Path
    docir_path: Path
    chunk_path: Path
    manifest_path: Path


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.partial")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _secure_artifact_tree(root: Path) -> None:
    """Apply private modes to one server-generated, symlink-free tree."""

    for current_root, directories, files in os.walk(root):
        current = Path(current_root)
        if current.is_symlink():
            raise RuntimeError("personal artifact tree contains a symlink")
        os.chmod(current, 0o700)
        for name in directories:
            path = current / name
            if path.is_symlink():
                raise RuntimeError("personal artifact tree contains a symlink")
        for name in files:
            path = current / name
            if path.is_symlink():
                raise RuntimeError("personal artifact tree contains a symlink")
            os.chmod(path, 0o600)


def _text(element_id: str, value: str, *, exact: bool) -> TextContent:
    layer_id = f"text_{element_id}"
    return TextContent(
        primary_layer_id=layer_id,
        layers=(
            TextLayer(
                text_layer_id=layer_id,
                origin=TextOrigin.NATIVE_TEXT if exact else TextOrigin.PARSER_DERIVED,
                text=value,
                quote_eligible=exact,
            ),
        ),
    )


def _pointer_token(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _json_leaves(value: Any, pointer: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _json_leaves(child, f"{pointer}/{_pointer_token(key)}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _json_leaves(child, f"{pointer}/{index}")
    else:
        yield pointer, value


class PersonalKnowledgeBaseIngestion:
    """Always produce persistent DocIR and Chunk artifacts; never direct-route."""

    def __init__(
        self,
        artifact_root: str | Path,
        *,
        mineru_parser: DocumentParser,
        chunk_config: ChunkConfig | None = None,
        visual_enrichment: Any | None = None,
        office_preview_converter: LibreOfficePreviewConverter | None = None,
        max_pages: int = 5000,
        max_assets: int = 10000,
    ) -> None:
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.mineru_parser = mineru_parser
        self.chunk_config = chunk_config or ChunkConfig()
        self.visual_enrichment = visual_enrichment
        self.office_preview_converter = office_preview_converter
        self.max_pages = max_pages
        self.max_assets = max_assets

    @property
    def pipeline_fingerprint(self) -> str:
        return configuration_sha256(
            {
                "schema": "personal-ingestion-0.3",
                "native_parser": NATIVE_PARSER_VERSION,
                "mineru_parser": self.mineru_parser.configuration_fingerprint,
                "vision": (
                    self.visual_enrichment.vision.configuration_fingerprint
                    if self.visual_enrichment is not None
                    else "disabled"
                ),
                "office_preview": (
                    self.office_preview_converter.configuration_fingerprint
                    if self.office_preview_converter is not None
                    else "disabled"
                ),
                "chunk_config": self.chunk_config.model_dump(mode="json"),
                "locator_schema": LOCATOR_SCHEMA_VERSION,
                "max_pages": self.max_pages,
                "max_assets": self.max_assets,
            }
        )

    async def ingest(
        self,
        *,
        file_id: str,
        filename: str,
        media_type: str,
        source_path: str | Path,
        source_sha256: str,
    ) -> PersonalIngestionResult:
        source = Path(source_path).resolve(strict=True)
        if file_sha256(source) != source_sha256:
            raise ValueError("personal knowledge-base source SHA-256 changed")
        suffix = source.suffix.lower()
        if suffix not in NATIVE_SUFFIXES | MINERU_SUFFIXES:
            raise ValueError(f"unsupported personal ingestion suffix: {suffix}")
        final_root = self.artifact_root / file_id / self.pipeline_fingerprint[:24]
        cached = self._load_cached(final_root, source_sha256)
        if cached is not None:
            return cached
        parent = final_root.parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        partial = parent / f".{final_root.name}.{uuid.uuid4().hex}.partial"
        partial.mkdir(mode=0o700)
        warnings: list[str] = []
        try:
            docir_root = partial / "docir"
            docir_root.mkdir()
            if suffix in NATIVE_SUFFIXES:
                document = self._parse_native(
                    source=source,
                    output_root=docir_root,
                    file_id=file_id,
                    filename=filename,
                    media_type=media_type,
                    source_sha256=source_sha256,
                )
            else:
                check_available = getattr(self.mineru_parser, "check_available", None)
                if callable(check_available):
                    await asyncio.to_thread(check_available)
                parsed = await asyncio.to_thread(
                    self.mineru_parser.parse, source, docir_root
                )
                parsed_document = parsed.document
                if self.visual_enrichment is not None:
                    try:
                        enriched = await self.visual_enrichment.enrich(
                            parsed_document, parsed.document_root
                        )
                        parsed_document = enriched.document
                    except Exception as exc:
                        warnings.append(
                            f"visual_enrichment_failed:{type(exc).__name__}"
                        )
                        logger.warning(
                            "personal visual enrichment degraded file_id=%s "
                            "error_type=%s",
                            file_id,
                            type(exc).__name__,
                        )
                document = self._normalize_mineru_document(
                    parsed_document,
                    suffix=suffix,
                    filename=filename,
                )
                page_count = document.source_page_count or document.parsed_page_count
                if page_count > self.max_pages:
                    raise ValueError("document page count exceeds personal limit")
                if len(document.assets) > self.max_assets:
                    raise ValueError("document asset count exceeds personal limit")
                save_document(document, docir_root / "document.json")
            docir_path = docir_root / "document.json"
            chunked = ChunkBuilder(self.chunk_config).build(
                document, docir_sha256=file_sha256(docir_path)
            )
            if not chunked.chunks:
                raise ValueError("document produced no retrievable chunks")
            chunk_path = partial / "chunks.json"
            save_json(chunked, chunk_path)
            preview_path = partial / "preview.txt"
            self._write_text_preview(chunked, preview_path)
            office_preview_path: Path | None = None
            if suffix in _OFFICE_SUFFIXES:
                if self.office_preview_converter is None:
                    warnings.append("office_pdf_preview_unavailable")
                else:
                    conversion_root = partial / ".office-preview-work"
                    try:
                        converted = self.office_preview_converter.convert(
                            source, conversion_root
                        )
                        office_preview_path = partial / "preview.pdf"
                        self.office_preview_converter.commit(
                            converted, office_preview_path
                        )
                    except Exception as exc:
                        warnings.append(
                            f"office_pdf_preview_failed:{type(exc).__name__}"
                        )
                        logger.warning(
                            "personal Office preview degraded file_id=%s error_type=%s",
                            file_id,
                            type(exc).__name__,
                        )
                    finally:
                        shutil.rmtree(conversion_root, ignore_errors=True)
            manifest_path = partial / "manifest.json"
            _atomic_json(
                manifest_path,
                {
                    "schema_version": "personal-ingestion-run-0.1",
                    "status": "ready",
                    "file_id": file_id,
                    "source_sha256": source_sha256,
                    "pipeline_fingerprint": self.pipeline_fingerprint,
                    "locator_schema_version": LOCATOR_SCHEMA_VERSION,
                    "document_id": document.document_id,
                    "docir_sha256": file_sha256(docir_path),
                    "chunk_sha256": file_sha256(chunk_path),
                    "preview_sha256": file_sha256(preview_path),
                    "office_preview_sha256": (
                        file_sha256(office_preview_path)
                        if office_preview_path is not None
                        else None
                    ),
                    "chunk_count": len(chunked.chunks),
                    "warnings": warnings,
                },
            )
            if final_root.exists():
                shutil.rmtree(partial)
            else:
                _secure_artifact_tree(partial)
                os.replace(partial, final_root)
            result = self._load_cached(final_root, source_sha256)
            if result is None:
                raise ValueError("committed personal ingestion artifacts failed validation")
            return result
        except BaseException:
            shutil.rmtree(partial, ignore_errors=True)
            raise

    def _load_cached(
        self, root: Path, source_sha256: str
    ) -> PersonalIngestionResult | None:
        manifest_path = root / "manifest.json"
        docir_path = root / "docir" / "document.json"
        chunk_path = root / "chunks.json"
        preview_path = root / "preview.txt"
        office_preview_path = root / "preview.pdf"
        if not all(
            path.is_file()
            for path in (manifest_path, docir_path, chunk_path, preview_path)
        ):
            return None
        try:
            manifest = json.loads(manifest_path.read_text("utf-8"))
            if (
                manifest.get("status") != "ready"
                or manifest.get("source_sha256") != source_sha256
                or manifest.get("pipeline_fingerprint") != self.pipeline_fingerprint
                or manifest.get("locator_schema_version") != LOCATOR_SCHEMA_VERSION
                or manifest.get("docir_sha256") != file_sha256(docir_path)
                or manifest.get("chunk_sha256") != file_sha256(chunk_path)
                or manifest.get("preview_sha256") != file_sha256(preview_path)
                or (
                    manifest.get("office_preview_sha256") is not None
                    and (
                        not office_preview_path.is_file()
                        or manifest.get("office_preview_sha256")
                        != file_sha256(office_preview_path)
                    )
                )
            ):
                return None
            document = load_document(docir_path)
            chunks = load_chunk_document(chunk_path)
            if len(chunks.chunks) != int(manifest["chunk_count"]):
                return None
            return PersonalIngestionResult(
                document=document,
                chunks=chunks,
                artifact_root=root,
                docir_path=docir_path,
                chunk_path=chunk_path,
                manifest_path=manifest_path,
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    @staticmethod
    def _write_text_preview(chunked: Any, output_path: Path) -> None:
        """Persist a bounded UTF-8 view without retaining the source binary."""

        remaining = _PREVIEW_TEXT_MAX_BYTES
        with output_path.open("xb") as stream:
            os.chmod(output_path, 0o600)
            for chunk in chunked.chunks:
                heading = " / ".join(chunk.section_path).strip()
                block = f"{heading}\n{chunk.bm25_body}" if heading else chunk.bm25_body
                encoded = (block.strip() + "\n\n").encode("utf-8")
                if len(encoded) > remaining:
                    encoded = encoded[:remaining].decode(
                        "utf-8", errors="ignore"
                    ).encode("utf-8")
                stream.write(encoded)
                remaining -= len(encoded)
                if remaining <= 0:
                    break
            stream.flush()
            os.fsync(stream.fileno())

    def discard_file_artifacts(self, file_id: str) -> None:
        """Remove only the server-generated artifact directory for one file."""

        uuid.UUID(file_id)
        directory = (self.artifact_root / file_id).resolve()
        directory.relative_to(self.artifact_root)
        shutil.rmtree(directory, ignore_errors=True)

    def _parse_native(
        self,
        *,
        source: Path,
        output_root: Path,
        file_id: str,
        filename: str,
        media_type: str,
        source_sha256: str,
    ) -> Document:
        suffix = source.suffix.lower()
        elements: list[HeadingElement | ParagraphElement] = []
        sections: list[Section] = []
        section_members: dict[str, list[str]] = {"section_root": []}
        section_titles: dict[str, str | None] = {"section_root": None}
        section_parents: dict[str, str | None] = {"section_root": None}

        def add(
            text: str,
            locator: Locator,
            *,
            section_id: str = "section_root",
            heading: bool = False,
            exact: bool = True,
        ) -> str:
            element_id = f"element_{len(elements):06d}"
            common = {
                "element_id": element_id,
                "document_order": len(elements),
                "role": ElementRole.BODY,
                "section_id": section_id,
                "locators": (locator.model_copy(update={"locator_id": f"locator_{element_id}"}),),
                "text": _text(element_id, text, exact=exact),
                "source_type": suffix.removeprefix("."),
            }
            element = (
                HeadingElement(**common, level=1)
                if heading
                else ParagraphElement(**common)
            )
            elements.append(element)
            section_members.setdefault(section_id, []).append(element_id)
            return element_id

        if suffix == ".txt":
            lines = source.read_text("utf-8").splitlines()
            index = 0
            while index < len(lines):
                if not lines[index].strip():
                    index += 1
                    continue
                start = index
                block = []
                while index < len(lines) and lines[index].strip():
                    block.append(lines[index])
                    index += 1
                add(
                    "\n".join(block),
                    Locator(
                        locator_id="pending", kind="text_lines",
                        schema_version=LOCATOR_SCHEMA_VERSION,
                        start_line=start + 1, end_line=index,
                    ),
                )
        elif suffix == ".md":
            lines = source.read_text("utf-8").splitlines()
            heading_stack: list[tuple[int, str, str]] = []
            current_section = "section_root"
            index = 0
            while index < len(lines):
                match = re.match(r"^(#{1,6})\s+(.+?)\s*$", lines[index])
                if match:
                    level, title = len(match.group(1)), match.group(2)
                    while heading_stack and heading_stack[-1][0] >= level:
                        heading_stack.pop()
                    parent = heading_stack[-1][2] if heading_stack else "section_root"
                    current_section = f"section_{len(section_members):06d}"
                    section_members[current_section] = []
                    section_parents[current_section] = parent
                    path = tuple(item[1] for item in heading_stack) + (title,)
                    title_id = add(
                        title,
                        Locator(
                            locator_id="pending", kind="markdown_section",
                            schema_version=LOCATOR_SCHEMA_VERSION,
                            start_line=index + 1, end_line=index + 1,
                            heading_path=path,
                        ),
                        section_id=current_section, heading=True,
                    )
                    section_titles[current_section] = title_id
                    heading_stack.append((level, title, current_section))
                    index += 1
                    continue
                if not lines[index].strip():
                    index += 1
                    continue
                start = index
                block = []
                while index < len(lines) and lines[index].strip() and not re.match(
                    r"^#{1,6}\s+", lines[index]
                ):
                    block.append(lines[index])
                    index += 1
                add(
                    "\n".join(block),
                    Locator(
                        locator_id="pending", kind="markdown_section",
                        schema_version=LOCATOR_SCHEMA_VERSION,
                        start_line=start + 1, end_line=index,
                        heading_path=tuple(item[1] for item in heading_stack),
                    ),
                    section_id=current_section,
                )
        elif suffix == ".csv":
            with source.open("r", encoding="utf-8", newline="") as stream:
                rows = list(csv.reader(stream))
            if not rows or not rows[0]:
                raise ValueError("CSV has no header")
            columns = tuple(rows[0])
            for start in range(1, len(rows), 50):
                selected = rows[start : start + 50]
                rendered = "\n".join(
                    ", ".join(
                        f"{columns[index]}={value}"
                        for index, value in enumerate(row[: len(columns)])
                    )
                    for row in selected
                )
                if rendered.strip():
                    add(
                        rendered,
                        Locator(
                            locator_id="pending", kind="csv_rows",
                            schema_version=LOCATOR_SCHEMA_VERSION,
                            start_row=start + 1, end_row=start + len(selected),
                            columns=columns,
                        ),
                        exact=False,
                    )
        else:
            value = json.loads(source.read_text("utf-8"))
            for pointer, leaf in _json_leaves(value):
                rendered = json.dumps(leaf, ensure_ascii=False)
                add(
                    f"{pointer or '/'}: {rendered}",
                    Locator(
                        locator_id="pending", kind="json_pointer",
                        schema_version=LOCATOR_SCHEMA_VERSION, pointer=pointer,
                    ),
                    exact=False,
                )
        if not elements:
            raise ValueError("native document contains no retrievable text")
        for section_id, members in section_members.items():
            sections.append(
                Section(
                    section_id=section_id,
                    parent_section_id=section_parents.get(section_id),
                    title_element_id=section_titles.get(section_id),
                    element_ids=tuple(members),
                )
            )
        assets = output_root / "assets"
        assets.mkdir()
        copied_source = assets / f"source{suffix}"
        with source.open("rb") as input_stream, copied_source.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        config = {
            "locator_schema_version": LOCATOR_SCHEMA_VERSION,
            "suffix": suffix,
        }
        document = Document(
            document_id=f"personal_doc_{file_id}",
            created_at=datetime.now(timezone.utc),
            source=SourceVersion(
                source_version_id=f"personal_source_{source_sha256[:24]}",
                filename=filename,
                media_type=media_type,
                byte_size=source.stat().st_size,
                sha256=source_sha256,
                original_asset_id=f"asset_{file_id}",
            ),
            parse_revision=ParseRevision(
                parse_revision_id=f"personal_parse_{configuration_sha256(config)[:24]}",
                parser_name="esa-personal-native",
                parser_version=NATIVE_PARSER_VERSION,
                config=config,
                config_sha256=configuration_sha256(config),
            ),
            title=filename,
            parsed_page_count=0,
            pages=(),
            sections=tuple(sections),
            elements=tuple(elements),
            assets=(
                Asset(
                    asset_id=f"asset_{file_id}", kind=AssetKind.ORIGINAL,
                    path=f"assets/source{suffix}", media_type=media_type,
                    byte_size=source.stat().st_size, sha256=source_sha256,
                ),
            ),
            validation=ValidationSummary(status=ValidationStatus.PASSED),
        )
        save_document(document, output_root / "document.json")
        return document

    def _normalize_mineru_document(
        self, document: Document, *, suffix: str, filename: str
    ) -> Document:
        section_paths = self._section_paths(document)
        values = document.model_dump(mode="python")
        values["source"]["filename"] = filename
        for element in values["elements"]:
            locators = element.get("locators", ())
            normalized = []
            for index, locator in enumerate(locators):
                bbox = locator.get("bbox")
                page = locator.get("container_index")
                common = {
                    "locator_id": locator["locator_id"],
                    "schema_version": LOCATOR_SCHEMA_VERSION,
                    "bbox": bbox,
                }
                if suffix == ".pdf":
                    if page is None or bbox is None:
                        continue
                    normalized.append(
                        Locator(**common, kind="pdf_region", page=int(page) + 1)
                    )
                elif suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                    asset_id = next(
                        iter(element.get("related_asset_ids", ())),
                        document.source.original_asset_id,
                    )
                    if bbox is None:
                        continue
                    normalized.append(
                        Locator(
                            **common, kind="image_region", asset_id=asset_id,
                            ocr_region=f"region-{index + 1}",
                        )
                    )
                else:
                    group_id = element["element_id"]
                    provenance = element.get("provenance", ())
                    if provenance and provenance[0].get("group_index") is not None:
                        group_id = f"group-{provenance[0]['group_index']}"
                    normalized.append(
                        Locator(
                            **common, kind="mineru_section", group_id=group_id,
                            section_path=section_paths.get(
                                element.get("section_id"), ()
                            ),
                            page=int(page) + 1 if page is not None else None,
                        )
                    )
            if element.get("text") is not None and not normalized:
                raise ValueError(
                    f"MinerU element lacks required personal locator: {element['element_id']}"
                )
            element["locators"] = tuple(normalized)
        return Document.model_validate(values)

    @staticmethod
    def _section_paths(document: Document) -> dict[str | None, tuple[str, ...]]:
        sections = {section.section_id: section for section in document.sections}
        elements = {element.element_id: element for element in document.elements}
        cache: dict[str | None, tuple[str, ...]] = {None: ()}

        def title(section_id: str) -> str | None:
            title_id = sections[section_id].title_element_id
            element = elements.get(title_id) if title_id else None
            if element is None or element.text is None:
                return None
            layer = next(
                item for item in element.text.layers
                if item.text_layer_id == element.text.primary_layer_id
            )
            return layer.text

        def path(section_id: str | None) -> tuple[str, ...]:
            if section_id in cache:
                return cache[section_id]
            section = sections[section_id]
            parent = path(section.parent_section_id)
            value = title(section_id)
            cache[section_id] = parent + ((value,) if value else ())
            return cache[section_id]

        for section_id in sections:
            path(section_id)
        return cache
