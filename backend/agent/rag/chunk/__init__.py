# backend/agent/rag/chunk/__init__.py

"""

这个文件干什么：独立 Chunk 模块公共入口。

直白点说就是：其他代码要切分文档或读取 Chunk 时从这里统一导入。

独立 Chunk 模块公共入口。
"""

from .builder import ChunkBuilder
from .docir_adapter import build_from_path, discover_docir_documents
from .models import (
    Chunk,
    ChunkCollection,
    ChunkConfig,
    ChunkDocument,
    ChunkDocumentRef,
    ChunkEvidence,
    ElementDisposition,
)
from .serializer import file_sha256, load_chunk_document, load_manifest, save_json
from .stats import collection_stats
from .table import parse_table_rows
from .text import split_text_spans

__all__ = [
    "Chunk",
    "ChunkBuilder",
    "ChunkCollection",
    "ChunkConfig",
    "ChunkDocument",
    "ChunkDocumentRef",
    "ChunkEvidence",
    "ElementDisposition",
    "build_from_path",
    "collection_stats",
    "discover_docir_documents",
    "file_sha256",
    "load_chunk_document",
    "load_manifest",
    "parse_table_rows",
    "save_json",
    "split_text_spans",
]
