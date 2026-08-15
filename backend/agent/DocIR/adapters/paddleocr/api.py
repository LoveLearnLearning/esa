# backend/agent/DocIR/adapters/paddleocr/api.py

"""High-level, atomic source-to-DocIR API for PaddleOCR."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from ...core.document import Document
from ...io import save_document
from .bundle import PaddleOCRBundle
from .converter import build_converted_bundle
from .models import PaddleOCRAdapterConfig
from .runtime import run_paddleocr


def materialize_bundle(
    bundle: PaddleOCRBundle,
    source: Path,
    output_dir: Path,
    *,
    strict: bool = False,
) -> Document:
    """Atomically write a self-contained, replayable PaddleOCR DocIR bundle."""

    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError(f"DocIR 输出目录已存在: {output}")
    if not output.parent.is_dir():
        raise FileNotFoundError(f"DocIR 输出父目录不存在: {output.parent}")
    converted = build_converted_bundle(bundle, source, strict=strict)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        for relative, content in converted.files.items():
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        save_document(converted.document, temporary / "document.json")
        os.replace(temporary, output)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return converted.document


def convert_source(
    source: Path,
    output_dir: Path,
    config: PaddleOCRAdapterConfig | None = None,
    *,
    strict: bool = False,
) -> Document:
    """Run PP-StructureV3 and atomically materialize the resulting DocIR."""

    source = Path(source).resolve()
    return materialize_bundle(
        run_paddleocr(source, config), source, output_dir, strict=strict
    )
