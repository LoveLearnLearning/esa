# backend/agent/rag/chunk/docir_adapter.py

"""

这个文件干什么：DocIR 文件发现、加载与 ChunkBuilder 适配。

直白点说就是：在磁盘上找到 DocIR 文档、读入它们，然后交给 ChunkBuilder 进行切分。

DocIR 文件发现、加载与 ChunkBuilder 适配。
"""

from __future__ import annotations

from pathlib import Path

from backend.agent.DocIR.io import load_document

from .builder import ChunkBuilder
from .models import ChunkDocument
from .serializer import file_sha256


def discover_docir_documents(input_root: Path) -> list[Path]:
    """发现 run 下逐文档 document.json，排除顶层 Schema 等文件。"""
    return sorted(
        (path for path in Path(input_root).glob("*/document.json") if path.is_file()),
        key=lambda path: path.parent.name,
    )


def build_from_path(path: Path, builder: ChunkBuilder) -> ChunkDocument:
    path = Path(path)
    return builder.build(load_document(path), docir_sha256=file_sha256(path))
