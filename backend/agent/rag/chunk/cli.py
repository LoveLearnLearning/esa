# backend/agent/rag/chunk/cli.py

"""

这个文件干什么：构建逐文档 ChunkDocument 与总 ChunkCollection。

直白点说就是：提供命令行入口，批量把 DocIR 文件切成 Chunk，并汇总成一个可索引集合。

构建逐文档 ChunkDocument 与总 ChunkCollection。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.agent.DocIR.core import Document
from backend.agent.DocIR.io import load_document

from ..paths import WORKSPACE_ROOT
from .builder import ChunkBuilder
from .docir_adapter import discover_docir_documents
from .models import (
    ChunkCollection,
    ChunkConfig,
    ChunkDocument,
    ChunkDocumentRef,
    canonical_sha256,
)
from .serializer import file_sha256, load_chunk_document, load_manifest, save_json
from .stats import CollectionStats, collection_stats

WORKSPACE = WORKSPACE_ROOT
DEFAULT_INPUT = WORKSPACE / "artifacts/docir/runs/full-corpus-20260802"
DEFAULT_OUTPUT = WORKSPACE / "artifacts/chunk/collections"


def _collection_id(
    documents: list[tuple[Path, Document]],
    config: ChunkConfig,
) -> str:
    identity = sorted(
        (document.document_id, document.parse_revision.parse_revision_id)
        for _path, document in documents
    )
    return f"collection_{canonical_sha256((identity, config.sha256, 'chunk-collection-0.1'))[:24]}"


def _resume_document(
    path: Path,
    source: tuple[Path, Document],
    config: ChunkConfig,
    expected_ref: ChunkDocumentRef | None,
) -> ChunkDocument:
    if expected_ref is None:
        raise ValueError(f"已有 ChunkDocument 没有 manifest 验证记录: {path}")
    if expected_ref.path != path.relative_to(path.parents[2]).as_posix():
        raise ValueError(f"manifest 路径与已有 ChunkDocument 不一致: {path}")
    if file_sha256(path) != expected_ref.sha256:
        raise ValueError(f"已有 ChunkDocument SHA-256 与 manifest 不一致: {path}")
    document = load_chunk_document(path)
    expected_hash = file_sha256(source[0])
    source_document = source[1]
    if (
        document.docir_sha256 != expected_hash
        or document.chunk_config_sha256 != config.sha256
        or document.document_id != source_document.document_id
        or document.parse_revision_id != source_document.parse_revision.parse_revision_id
    ):
        raise ValueError(f"已有 ChunkDocument 与当前输入/配置不一致: {path}")
    return document


def build_collection(
    input_root: Path,
    output_root: Path,
    config: ChunkConfig,
    *,
    resume: bool = True,
) -> tuple[Path, ChunkCollection, CollectionStats]:
    paths = discover_docir_documents(input_root)
    if not paths:
        raise ValueError(f"没有发现 DocIR document.json: {input_root}")
    sources = [(path, load_document(path)) for path in paths]
    collection_id = _collection_id(sources, config)
    collection_root = Path(output_root) / collection_id
    documents_root = collection_root / "documents"
    documents_root.mkdir(parents=True, exist_ok=True)
    manifest_path = collection_root / "manifest.json"
    existing_refs: dict[str, ChunkDocumentRef] = {}
    if resume and manifest_path.is_file():
        existing = load_manifest(manifest_path)
        if existing.collection_id != collection_id or existing.chunk_config_sha256 != config.sha256:
            raise ValueError(f"已有 manifest 与当前语料/配置不一致: {manifest_path}")
        existing_refs = {item.document_id: item for item in existing.documents}
    builder = ChunkBuilder(config)
    built: list[ChunkDocument] = []
    refs: list[ChunkDocumentRef] = []
    for source in sources:
        source_path, source_document = source
        relative = Path("documents") / source_path.parent.name / "chunks.json"
        target = collection_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if resume and target.is_file():
            chunk_document = _resume_document(
                target,
                source,
                config,
                existing_refs.get(source_document.document_id),
            )
        else:
            chunk_document = builder.build(source_document, docir_sha256=file_sha256(source_path))
            save_json(chunk_document, target)
        digest = file_sha256(target)
        built.append(chunk_document)
        refs.append(
            ChunkDocumentRef(
                document_id=chunk_document.document_id,
                source_version_id=chunk_document.source_version_id,
                parse_revision_id=chunk_document.parse_revision_id,
                chunk_revision_id=chunk_document.chunk_revision_id,
                path=relative.as_posix(),
                sha256=digest,
                chunk_count=len(chunk_document.chunks),
            )
        )
    refs.sort(key=lambda item: item.document_id)
    manifest = ChunkCollection(
        collection_id=collection_id,
        chunk_config=config,
        chunk_config_sha256=config.sha256,
        documents=tuple(refs),
        document_count=len(refs),
        chunk_count=sum(item.chunk_count for item in refs),
    )
    stats = collection_stats(built)
    save_json(manifest, manifest_path)
    save_json(stats, collection_root / "stats.json")
    return collection_root, manifest, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 DocIR V0.2 run 构建 ChunkCollection")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--target-chars", type=int, default=800)
    parser.add_argument("--max-chars", type=int, default=1200)
    parser.add_argument("--overlap-elements", type=int, choices=(0, 1), default=1)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(argv)
    config = ChunkConfig(
        target_chars=args.target_chars,
        max_chars=args.max_chars,
        overlap_elements=args.overlap_elements,
    )
    root, manifest, stats = build_collection(
        args.input_root,
        args.output_root,
        config,
        resume=args.resume,
    )
    print(f"collection_root={root}")
    print(f"documents={manifest.document_count} chunks={manifest.chunk_count}")
    print(f"max_body_chars={stats['chunk_length']['max']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
