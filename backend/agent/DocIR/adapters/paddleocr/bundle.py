"""Replayable, lossless representation of one PP-StructureV3 run."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RAW_RESULTS_NAME = "paddleocr_results.json"
RAW_METADATA_NAME = "conversion_metadata.json"


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def page_image_path(page_index: int) -> str:
    return f"assets/pages/page-{page_index + 1:06d}.png"


@dataclass(frozen=True)
class PaddleOCRBundle:
    """Raw per-page PaddleOCR JSON plus the exact page rasters it describes."""

    pages: tuple[dict[str, Any], ...]
    page_images: tuple[bytes, ...]
    status: str
    version: dict[str, Any]
    config: dict[str, Any]
    errors: tuple[dict[str, Any], ...] = ()
    root: Path | None = None

    def __post_init__(self) -> None:
        if len(self.pages) != len(self.page_images):
            raise ValueError("PaddleOCR pages 与 page_images 数量不一致")

    @property
    def results_bytes(self) -> bytes:
        return _json_bytes({"pages": list(self.pages)})

    @property
    def metadata_bytes(self) -> bytes:
        return _json_bytes(
            {
                "status": self.status,
                "version": self.version,
                "config": self.config,
                "errors": list(self.errors),
                "page_image_paths": [
                    page_image_path(index) for index in range(len(self.pages))
                ],
            }
        )


def load_bundle(path: Path) -> PaddleOCRBundle:
    """Load a previously materialized PaddleOCR raw bundle."""

    supplied = Path(path).resolve()
    raw = supplied if supplied.name == "raw" else supplied / "raw"
    root = raw.parent
    results_path = raw / RAW_RESULTS_NAME
    metadata_path = raw / RAW_METADATA_NAME
    if not results_path.is_file() or not metadata_path.is_file():
        raise FileNotFoundError(
            f"PaddleOCR bundle 缺少 {RAW_RESULTS_NAME} 或 {RAW_METADATA_NAME}: {supplied}"
        )
    results = json.loads(results_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(results, dict) or not isinstance(results.get("pages"), list):
        raise TypeError("PaddleOCR results 顶层必须包含 pages 数组")
    if not isinstance(metadata, dict):
        raise TypeError("PaddleOCR conversion metadata 顶层必须是对象")
    image_paths = metadata.get("page_image_paths")
    if not isinstance(image_paths, list):
        raise TypeError("PaddleOCR metadata 缺少 page_image_paths 数组")
    images = tuple((root / str(relative)).read_bytes() for relative in image_paths)
    pages = tuple(dict(page) for page in results["pages"])
    return PaddleOCRBundle(
        pages=pages,
        page_images=images,
        status=str(metadata.get("status", "unknown")),
        version=dict(metadata.get("version") or {}),
        config=dict(metadata.get("config") or {}),
        errors=tuple(metadata.get("errors") or ()),
        root=root,
    )
