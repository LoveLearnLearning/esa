"""High-level, atomic source-to-DocIR bundle API."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from ...core.document import Document
from ...io import save_document
from .bundle import DoclingBundle
from .converter import build_converted_bundle
from .models import DoclingAdapterConfig
from .runtime import run_docling


def materialize_bundle(
    bundle: DoclingBundle,
    source: Path,
    output_dir: Path,
    *,
    strict: bool = False,
) -> Document:
    """Atomically materialize an existing conversion as a self-contained bundle."""

    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError(f"DocIR 输出目录已存在: {output}")
    if not output.parent.is_dir():
        raise FileNotFoundError(f"DocIR 输出父目录不存在: {output.parent}")
    converted = build_converted_bundle(bundle, source, strict=strict)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent)
    )
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
    config: DoclingAdapterConfig | None = None,
    *,
    strict: bool = False,
) -> Document:
    """Run Docling and atomically write a complete DocIR bundle."""

    source = Path(source).resolve()
    bundle = run_docling(source, config)
    return materialize_bundle(bundle, source, output_dir, strict=strict)
