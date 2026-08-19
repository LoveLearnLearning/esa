# backend/agent/rag/collection.py

"""
这个文件干什么：ChunkCollection 的严格运行时加载视图。

直白点说就是：按清单把多个 Chunk 文档安全地加载进内存，同时核对路径、哈希和数量没有被篡改。

ChunkCollection 的严格运行时加载视图。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .chunk import Chunk, ChunkCollection, ChunkDocument
from .chunk.serializer import load_chunk_document, load_manifest


@dataclass(frozen=True)
class LoadedChunkCollection:
    """已验证并完整载入内存的 ChunkCollection。"""

    root: Path
    manifest_path: Path
    manifest_sha256: str
    manifest: ChunkCollection
    documents: tuple[ChunkDocument, ...]
    chunks: tuple[Chunk, ...]
    document_names: Mapping[str, str]


def _file_sha256(path: Path) -> str:
    """处理 `_file_sha256` 相关逻辑。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_chunk_collection(manifest_path: Path) -> LoadedChunkCollection:
    """加载 manifest 及全部 ChunkDocument，并拒绝任何身份或哈希偏差。"""

    manifest_path = manifest_path.resolve(strict=True)
    root = manifest_path.parent
    manifest = load_manifest(manifest_path)
    documents: list[ChunkDocument] = []
    chunks: list[Chunk] = []
    document_names: dict[str, str] = {}

    for reference in manifest.documents:
        candidate = (root / reference.path).resolve(strict=True)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("ChunkDocument 路径越出 Collection 根目录") from exc
        actual_sha256 = _file_sha256(candidate)
        if actual_sha256 != reference.sha256:
            raise ValueError(f"ChunkDocument SHA-256 不一致: {reference.path}")
        document = load_chunk_document(candidate)
        identity = (
            document.document_id,
            document.source_version_id,
            document.parse_revision_id,
            document.chunk_revision_id,
            len(document.chunks),
        )
        expected = (
            reference.document_id,
            reference.source_version_id,
            reference.parse_revision_id,
            reference.chunk_revision_id,
            reference.chunk_count,
        )
        if identity != expected:
            raise ValueError(f"ChunkDocument 身份与 manifest 不一致: {reference.path}")
        if document.chunk_config_sha256 != manifest.chunk_config_sha256:
            raise ValueError(
                f"ChunkDocument 配置与 Collection 不一致: {reference.path}"
            )
        documents.append(document)
        chunks.extend(document.chunks)
        document_names[document.document_id] = document.filename

    chunk_ids = [chunk.chunk_id for chunk in chunks]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("Collection 内 chunk_id 不能重复")
    if len(chunks) != manifest.chunk_count:
        raise ValueError("Collection 实际 Chunk 数与 manifest 不一致")
    if len(documents) != manifest.document_count:
        raise ValueError("Collection 实际文档数与 manifest 不一致")

    return LoadedChunkCollection(
        root=root,
        manifest_path=manifest_path,
        manifest_sha256=_file_sha256(manifest_path),
        manifest=manifest,
        documents=tuple(documents),
        chunks=tuple(chunks),
        document_names=MappingProxyType(document_names),
    )
