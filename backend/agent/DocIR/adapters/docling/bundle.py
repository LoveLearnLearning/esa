# backend/agent/DocIR/adapters/docling/bundle.py

"""In-memory and on-disk representation of one Docling conversion."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docling_core.types.doc import DoclingDocument

RAW_DOCUMENT_NAME = "docling_document.json"
RAW_METADATA_NAME = "conversion_metadata.json"


def _json_bytes(value: Any) -> bytes:
    """处理 `_json_bytes` 相关逻辑。"""
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


@dataclass(frozen=True)
class DoclingBundle:
    """The lossless Docling document plus auditable conversion metadata."""

    document: DoclingDocument
    status: str
    version: dict[str, Any]
    config: dict[str, Any]
    errors: tuple[dict[str, Any], ...] = ()
    timestamp: str | None = None
    timings: dict[str, Any] = field(default_factory=dict)
    root: Path | None = None

    @property
    def document_bytes(self) -> bytes:
        """处理 `document_bytes` 相关逻辑。"""
        return _json_bytes(
            self.document.model_dump(mode="json", by_alias=True)
        )

    @property
    def metadata_bytes(self) -> bytes:
        """处理 `metadata_bytes` 相关逻辑。"""
        return _json_bytes(
            {
                "status": self.status,
                "version": self.version,
                "config": self.config,
                "errors": list(self.errors),
                "timestamp": self.timestamp,
                "timings": self.timings,
            }
        )


def load_bundle(path: Path) -> DoclingBundle:
    """Load a raw Docling bundle saved by :func:`convert_source`."""

    root = Path(path)
    raw = root / "raw" if (root / "raw").is_dir() else root
    document_path = raw / RAW_DOCUMENT_NAME
    metadata_path = raw / RAW_METADATA_NAME
    if not document_path.is_file() or not metadata_path.is_file():
        raise FileNotFoundError(
            f"Docling bundle 缺少 {RAW_DOCUMENT_NAME} 或 {RAW_METADATA_NAME}: {root}"
        )
    document = DoclingDocument.model_validate_json(document_path.read_bytes())
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise TypeError("Docling conversion metadata 顶层必须是对象")
    return DoclingBundle(
        document=document,
        status=str(metadata.get("status", "unknown")),
        version=dict(metadata.get("version") or {}),
        config=dict(metadata.get("config") or {}),
        errors=tuple(metadata.get("errors") or ()),
        timestamp=metadata.get("timestamp"),
        timings=dict(metadata.get("timings") or {}),
        root=root,
    )
