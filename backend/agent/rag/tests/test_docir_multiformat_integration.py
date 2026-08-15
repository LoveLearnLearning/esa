# backend/agent/rag/tests/test_docir_multiformat_integration.py

"""真实 Office fixture 到 DocIR、Chunk、Index 与 Retrieval 的完整回归。"""

from pathlib import Path
from types import MappingProxyType

import pytest

from backend.agent.DocIR.adapters.mineru import convert_bundle, load_bundle
from backend.agent.rag.chunk import (
    ChunkBuilder,
    ChunkCollection,
    ChunkDocumentRef,
)
from backend.agent.rag.collection import LoadedChunkCollection
from backend.agent.rag.indexes import ReferenceIndex
from backend.agent.rag.indexing import IndexingService
from backend.agent.rag.inference import HashingEmbeddingProvider, LexicalOverlapReranker
from backend.agent.rag.retrieval.contracts import RetrievalConfig
from backend.agent.rag.retrieval.service import RetrievalService

DOCIR_ROOT = Path(__file__).resolve().parents[2] / "DocIR"
FIXTURE_ROOT = DOCIR_ROOT / "tests/fixtures/mineru_adapter/outputs"
SOURCE_ROOT = DOCIR_ROOT / "mineru_adapter_samples"
OFFICE_CASES = {
    "DOCX": ("docx_mixed", "docx_mixed.docx", "DOCX_MIXED_ANCHOR_001"),
    "PPTX": ("pptx_mixed", "pptx_mixed.pptx", "PPTX_TITLE_ANCHOR_001"),
    "XLSX": ("xlsx_mixed", "xlsx_mixed.xlsx", "XLSX_SUMMARY_ANCHOR_001"),
}
pytestmark = pytest.mark.skipif(
    not FIXTURE_ROOT.is_dir() or not SOURCE_ROOT.is_dir(),
    reason="external multiformat MinerU regression data is unavailable",
)


def _chunk_documents():
    """处理 `_chunk_documents` 相关逻辑。"""
    output = []
    for name, filename, _marker in OFFICE_CASES.values():
        middle = next((FIXTURE_ROOT / name).rglob("*_middle.json"))
        document = convert_bundle(
            load_bundle(middle.parent),
            SOURCE_ROOT / filename,
            strict=True,
        )
        output.append(ChunkBuilder().build(document, docir_sha256="c" * 64))
    return tuple(output)


def _collection(tmp_path: Path) -> LoadedChunkCollection:
    """处理 `_collection` 相关逻辑。"""
    documents = _chunk_documents()
    config = documents[0].chunk_config
    references = tuple(
        ChunkDocumentRef(
            document_id=document.document_id,
            source_version_id=document.source_version_id,
            parse_revision_id=document.parse_revision_id,
            chunk_revision_id=document.chunk_revision_id,
            path=f"{document.document_id}.json",
            sha256="d" * 64,
            chunk_count=len(document.chunks),
        )
        for document in documents
    )
    manifest = ChunkCollection(
        collection_id="office-fixtures",
        chunk_config=config,
        chunk_config_sha256=config.sha256,
        documents=references,
        document_count=len(documents),
        chunk_count=sum(len(document.chunks) for document in documents),
    )
    return LoadedChunkCollection(
        root=tmp_path,
        manifest_path=tmp_path / "manifest.json",
        manifest_sha256="e" * 64,
        manifest=manifest,
        documents=documents,
        chunks=tuple(chunk for document in documents for chunk in document.chunks),
        document_names=MappingProxyType(
            {document.document_id: document.filename for document in documents}
        ),
    )


@pytest.mark.parametrize("format_name", OFFICE_CASES)
def test_office_chunks_have_non_spatial_evidence(format_name: str) -> None:
    """验证 `office_chunks_have_non_spatial_evidence` 场景。"""
    name, filename, marker = OFFICE_CASES[format_name]
    middle = next((FIXTURE_ROOT / name).rglob("*_middle.json"))
    document = convert_bundle(load_bundle(middle.parent), SOURCE_ROOT / filename, strict=True)
    chunks = ChunkBuilder().build(document, docir_sha256="c" * 64)

    assert any(marker in chunk.bm25_body for chunk in chunks.chunks)
    assert all(
        locator.kind == "group" and locator.page_id is None and locator.bbox is None
        for chunk in chunks.chunks
        for evidence in chunk.evidence
        for locator in evidence.locators
    )


@pytest.mark.parametrize(
    ("query", "expected_filename"),
    [
        ("DOCX_MIXED_ANCHOR_001", "docx_mixed.docx"),
        ("PPTX_TITLE_ANCHOR_001", "pptx_mixed.pptx"),
        ("XLSX_SUMMARY_ANCHOR_001", "xlsx_mixed.xlsx"),
    ],
)
def test_office_docir_reaches_index_and_retrieval(
    tmp_path: Path,
    query: str,
    expected_filename: str,
) -> None:
    """验证 `office_docir_reaches_index_and_retrieval` 场景。"""
    collection = _collection(tmp_path)
    index = ReferenceIndex()
    embedding = HashingEmbeddingProvider()
    IndexingService(collection, index, embedding).build()
    service = RetrievalService(
        collection,
        index,
        embedding,
        LexicalOverlapReranker(),
        RetrievalConfig(final_limit=3, dense_weight=0.5),
    )

    response = service.search(query)

    assert response.hits
    assert response.hits[0].evidence[0].document_name == expected_filename
    assert response.hits[0].evidence[0].locators
