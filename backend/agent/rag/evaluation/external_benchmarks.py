"""Run ESA's retrieval pipeline against public retrieval/QA benchmarks.

The adapters in this module intentionally live in ``evaluation``.  They turn
benchmark records into an in-memory ChunkCollection without making benchmark
formats part of the production DocIR or chunk contracts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from backend.agent.DocIR.core.enums import TextOrigin
from backend.agent.DocIR.core.geometry import Locator

from ..chunk import (
    Chunk,
    ChunkCollection,
    ChunkConfig,
    ChunkDocumentRef,
    ChunkEvidence,
    ContentRole,
)
from ..chunk.models import canonical_sha256
from ..collection import LoadedChunkCollection
from ..fingerprints import configuration_sha256
from ..indexes.reference import reference_tokens
from ..indexing import IndexingService
from ..inference import HashingEmbeddingProvider, LexicalOverlapReranker
from ..retrieval.contracts import RankedItem, RetrievalConfig
from ..retrieval.service import RetrievalService


DEFAULT_DATA_ROOT = Path("artifacts/rag/benchmarks/datasets")
DEFAULT_OUTPUT_ROOT = Path("artifacts/rag/benchmarks/results")
M3DOCVQA_REVISION = "61639bd223e0e73f0e057df72504eccd61d00814"


@dataclass(frozen=True)
class CorpusPart:
    """One independently retrievable part of a benchmark document."""

    document_id: str
    title: str
    text: str
    page_index: int = 0


@dataclass(frozen=True)
class BenchmarkCase:
    """A query and its relevant document identities."""

    case_id: str
    query: str
    relevant_document_ids: frozenset[str]
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class BenchmarkData:
    """Normalized corpus and queries consumed by the common evaluator."""

    name: str
    scope: str
    parts: tuple[CorpusPart, ...]
    cases: tuple[BenchmarkCase, ...]
    source: Mapping[str, str]


@dataclass
class _FieldIndex:
    postings: dict[str, list[tuple[int, int]]]
    lengths: np.ndarray
    average_length: float


@dataclass
class CachedReferenceIndex:
    """ReferenceIndex-compatible backend with cached BM25 and NumPy dense search.

    The production reference backend favors minimal code for tiny regression
    fixtures.  Public benchmarks are large enough that recomputing tokenization
    for every query would dominate the measurement, so this evaluation-only
    backend preserves the same scoring formula while caching the corpus side.
    """

    chunks: list[Chunk] = field(default_factory=list)
    generation_id: str | None = None
    _vectors: np.ndarray | None = field(default=None, init=False, repr=False)
    _fields: dict[str, _FieldIndex] = field(default_factory=dict, init=False)

    @property
    def configuration_fingerprint(self) -> str:
        return configuration_sha256(
            {
                "backend": "evaluation-cached-reference-index-0.1",
                "bm25": {"k1": 1.2, "b": 0.75},
                "tokenizer": "reference-tokenizer-0.1",
                "dense": "numpy-dot-normalized-hashing-vectors",
            }
        )

    def prepare(
        self,
        dense_dimension: int,
        generation_id: str,
        expected_count: int,
    ) -> None:
        if dense_dimension <= 0 or not generation_id or expected_count < 0:
            raise ValueError("invalid index preparation arguments")

    def generation_is_ready(self, generation_id: str, expected_count: int) -> bool:
        return (
            self.generation_id == generation_id
            and len(self.chunks) == expected_count
            and self._vectors is not None
            and len(self._vectors) == expected_count
        )

    def build(
        self,
        chunks: Sequence[Chunk],
        dense_vectors: Sequence[Sequence[float]],
        *,
        generation_id: str,
    ) -> None:
        vectors = np.asarray(dense_vectors, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != len(chunks) or not vectors.shape[1]:
            raise ValueError("dense vectors must be a non-empty matrix")
        self.chunks = list(chunks)
        self._vectors = vectors
        self._fields = {
            name: self._make_field(name) for name in ("bm25_body", "bm25_heading")
        }
        self.generation_id = generation_id

    def _make_field(self, name: str) -> _FieldIndex:
        postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        lengths = np.zeros(len(self.chunks), dtype=np.int32)
        for index, chunk in enumerate(self.chunks):
            counts = Counter(reference_tokens(getattr(chunk, name)))
            lengths[index] = sum(counts.values())
            for token, count in counts.items():
                postings[token].append((index, count))
        return _FieldIndex(
            postings=dict(postings),
            lengths=lengths,
            average_length=float(lengths.mean()) if len(lengths) else 0.0,
        )

    @staticmethod
    def _roles_allow_body(content_roles: frozenset[ContentRole] | None) -> bool:
        return content_roles is None or ContentRole.BODY in content_roles

    def dense(
        self,
        query_vector: Sequence[float],
        limit: int,
        content_roles: frozenset[ContentRole] | None = None,
    ) -> list[RankedItem]:
        if not self._roles_allow_body(content_roles) or self._vectors is None:
            return []
        query = np.asarray(query_vector, dtype=np.float32)
        if query.ndim != 1 or query.shape[0] != self._vectors.shape[1]:
            raise ValueError("query vector dimension does not match index")
        scores = self._vectors @ query
        ordered = np.argsort(-scores, kind="stable")[:limit]
        return [RankedItem(self.chunks[i].chunk_id, float(scores[i])) for i in ordered]

    def _bm25(self, query: str, field_name: str, limit: int) -> list[RankedItem]:
        field_index = self._fields[field_name]
        query_counts = Counter(reference_tokens(query))
        scores: dict[int, float] = defaultdict(float)
        document_count = len(self.chunks)
        for token, query_frequency in query_counts.items():
            posting = field_index.postings.get(token, ())
            document_frequency = len(posting)
            if not document_frequency:
                continue
            inverse_document_frequency = math.log(
                1.0
                + (document_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            for index, frequency in posting:
                normalization = frequency + 1.2 * (
                    0.25
                    + 0.75
                    * float(field_index.lengths[index])
                    / (field_index.average_length or 1.0)
                )
                scores[index] += (
                    query_frequency
                    * inverse_document_frequency
                    * frequency
                    * 2.2
                    / normalization
                )
        ordered = sorted(scores, key=lambda i: (-scores[i], self.chunks[i].chunk_id))
        return [RankedItem(self.chunks[i].chunk_id, scores[i]) for i in ordered[:limit]]

    def bm25_body(
        self,
        query: str,
        limit: int,
        content_roles: frozenset[ContentRole] | None = None,
    ) -> list[RankedItem]:
        if not self._roles_allow_body(content_roles):
            return []
        return self._bm25(query, "bm25_body", limit)

    def bm25_heading(
        self,
        query: str,
        limit: int,
        content_roles: frozenset[ContentRole] | None = None,
    ) -> list[RankedItem]:
        if not self._roles_allow_body(content_roles):
            return []
        return self._bm25(query, "bm25_heading", limit)


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"expected object at {path}:{line_number}")
                yield value


def load_scifact(root: Path) -> BenchmarkData:
    """Load the official BEIR SciFact corpus and test qrels."""

    corpus_path = root / "corpus.jsonl"
    query_path = root / "queries.jsonl"
    qrels_path = root / "qrels/test.tsv"
    parts = tuple(
        CorpusPart(str(item["_id"]), str(item.get("title", "")), str(item["text"]))
        for item in _read_jsonl(corpus_path)
    )
    queries = {str(item["_id"]): str(item["text"]) for item in _read_jsonl(query_path)}
    relevant: dict[str, set[str]] = defaultdict(set)
    with qrels_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if int(row["score"]) > 0:
                relevant[row["query-id"]].add(row["corpus-id"])
    cases = tuple(
        BenchmarkCase(query_id, queries[query_id], frozenset(document_ids), ("test",))
        for query_id, document_ids in sorted(relevant.items())
    )
    return BenchmarkData(
        name="scifact",
        scope="official BEIR SciFact test retrieval",
        parts=parts,
        cases=cases,
        source={
            "url": "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip",
            "md5": "5f7d1de60b170fc8027bb7898e2efca1",
        },
    )


def load_xor_tydi_gold(root: Path) -> BenchmarkData:
    """Load XOR-TyDi's public dev GoldParagraph data.

    This is a candidate-paragraph retrieval evaluation, not the official
    XOR-Retrieve task, whose corpus is the eight-language 2019 Wikipedia dump.
    """

    path = root / "xorqa_reading_comprehension_format/gp_squad_dev_data.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    documents: dict[str, CorpusPart] = {}
    cases: list[BenchmarkCase] = []
    for article in payload["data"]:
        title = str(article["title"])
        for paragraph in article["paragraphs"]:
            context = str(paragraph["context"]).strip()
            document_id = f"xor_{canonical_sha256([title, context])[:24]}"
            documents.setdefault(document_id, CorpusPart(document_id, title, context))
            for qa in paragraph["qas"]:
                cases.append(
                    BenchmarkCase(
                        str(qa["id"]),
                        str(qa["question"]),
                        frozenset({document_id}),
                        (f"lang:{qa['lang']}", "dev", "gold-paragraph"),
                    )
                )
    return BenchmarkData(
        name="xor-tydi",
        scope="XOR-TyDi dev GoldParagraph candidate retrieval (not official XOR-Retrieve)",
        parts=tuple(documents.values()),
        cases=tuple(cases),
        source={
            "url": "https://nlp.cs.washington.edu/xorqa/XORQA_site/data/xorqa_reading_comprehension_format.zip",
            "license": "CC BY-SA 4.0",
        },
    )


def _extract_pdf(pdf_path: Path) -> tuple[str, list[str], str | None]:
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf_path), "-"],
            check=False,
            capture_output=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return pdf_path.stem, [], type(exc).__name__
    if result.returncode:
        return pdf_path.stem, [], result.stderr.decode("utf-8", "replace")[-500:]
    raw = result.stdout.decode("utf-8", "replace").replace("\x00", "")
    pages = ["\n".join(line.rstrip() for line in page.splitlines()).strip() for page in raw.split("\f")]
    return pdf_path.stem, pages, None


def extract_m3docvqa_text(root: Path, cache_path: Path, workers: int = 8) -> dict[str, int]:
    """Extract page text from the pinned M3DocVQA dev PDFs into JSONL."""

    document_ids = json.loads((root / "dev_doc_ids.json").read_text(encoding="utf-8"))
    pdf_paths = [root / "pdfs_dev" / f"{document_id}.pdf" for document_id in document_ids]
    missing = [path for path in pdf_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"M3DocVQA download is incomplete: {len(missing)} PDFs missing")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(".tmp")
    page_count = 0
    text_page_count = 0
    failed_count = 0
    with temporary.open("w", encoding="utf-8") as output:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for done, (document_id, pages, error) in enumerate(
                executor.map(_extract_pdf, pdf_paths), 1
            ):
                failed_count += int(error is not None)
                for page_index, page_text in enumerate(pages):
                    page_count += 1
                    if page_text:
                        text_page_count += 1
                        output.write(
                            json.dumps(
                                {
                                    "document_id": document_id,
                                    "page_index": page_index,
                                    "text": page_text,
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                if done % 250 == 0:
                    print(f"extracted_pdfs={done}/{len(pdf_paths)}", file=sys.stderr)
    temporary.replace(cache_path)
    return {
        "document_count": len(pdf_paths),
        "page_count": page_count,
        "text_page_count": text_page_count,
        "failed_document_count": failed_count,
    }


def load_m3docvqa(root: Path, cache_path: Path, workers: int = 8) -> BenchmarkData:
    """Load M3DocVQA dev PDFs as text pages and document-level gold labels."""

    document_ids = json.loads((root / "dev_doc_ids.json").read_text(encoding="utf-8"))
    if not cache_path.is_file():
        extraction_stats = extract_m3docvqa_text(root, cache_path, workers)
        cache_path.with_suffix(".stats.json").write_text(
            json.dumps(extraction_stats, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    parts = tuple(
        CorpusPart(
            str(item["document_id"]),
            str(item["document_id"]),
            str(item["text"]),
            int(item["page_index"]),
        )
        for item in _read_jsonl(cache_path)
        if str(item["text"]).strip()
    )
    cases: list[BenchmarkCase] = []
    for item in _read_jsonl(root / "multimodalqa/MMQA_dev.jsonl"):
        relevant = frozenset(str(value["doc_id"]) for value in item["supporting_context"])
        modalities = tuple(f"modality:{value}" for value in item["metadata"]["modalities"])
        cases.append(
            BenchmarkCase(
                str(item["qid"]),
                str(item["question"]),
                relevant,
                (f"type:{item['metadata']['type']}", *modalities, "dev"),
            )
        )
    return BenchmarkData(
        name="m3docvqa",
        scope="M3DocVQA dev document retrieval over pdftotext pages; visual-only evidence is unsupported",
        parts=parts,
        cases=tuple(cases),
        source={
            "url": "https://huggingface.co/datasets/ad6398/m3docvqa",
            "revision": M3DOCVQA_REVISION,
            "license": "Apache-2.0 metadata; source Wikipedia document rights remain upstream",
            "expected_dev_documents": str(len(document_ids)),
            "text_extraction": "pdftotext -layout",
        },
    )


def _split_text(text: str, max_chars: int = 1800) -> list[str]:
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(text) <= max_chars:
        return [text] if text else []
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundary = max(text.rfind("\n", start, end), text.rfind(". ", start, end))
            if boundary > start + max_chars // 2:
                end = boundary + 1
        part = text[start:end].strip()
        if part:
            parts.append(part)
        start = end
    return parts


def build_benchmark_collection(data: BenchmarkData) -> LoadedChunkCollection:
    """Create a deterministic, evaluation-only in-memory ChunkCollection."""

    chunks: list[Chunk] = []
    document_names: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for part in data.parts:
        document_names.setdefault(part.document_id, part.title or part.document_id)
        for part_index, text in enumerate(_split_text(part.text)):
            order = counts[part.document_id]
            counts[part.document_id] += 1
            identity = [data.name, part.document_id, part.page_index, part_index, text]
            suffix = canonical_sha256(identity)[:24]
            chunk_id = f"benchmark_chunk_{suffix}"
            element_id = f"benchmark_element_{suffix}"
            evidence_id = f"benchmark_evidence_{suffix}"
            dense_text = f"{part.title}\n{text}" if part.title else text
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    chunk_revision_id=f"benchmark_revision_{data.name}",
                    document_order=order,
                    document_id=part.document_id,
                    source_version_id=f"benchmark_source_{data.name}",
                    parse_revision_id=f"benchmark_parse_{data.name}",
                    section_id=f"page_{part.page_index}",
                    section_path=(part.title,) if part.title else (),
                    element_ids=(element_id,),
                    kind_counts={"benchmark_text": 1},
                    content_role=ContentRole.BODY,
                    retrieval_enabled=True,
                    dense_text=dense_text,
                    bm25_body=text,
                    bm25_heading=part.title or part.document_id,
                    body_char_count=len(text),
                    evidence=(
                        ChunkEvidence(
                            evidence_id=evidence_id,
                            element_id=element_id,
                            text=text,
                            text_origin=TextOrigin.NATIVE_OR_OCR_UNVERIFIED,
                            quote_eligible=False,
                            derivation="primary_text_span",
                            text_start=0,
                            text_end=len(text),
                            locators=(
                                Locator(
                                    locator_id=f"benchmark_locator_{suffix}",
                                    kind="page",
                                    container_id=f"page_{part.page_index}",
                                    container_index=part.page_index,
                                    page_id=f"page_{part.page_index}",
                                ),
                            ),
                        ),
                    ),
                )
            )

    maximum_chunk_chars = max(
        800,
        max((len(chunk.bm25_body) for chunk in chunks), default=1),
    )
    config = ChunkConfig(max_chars=maximum_chunk_chars)
    document_refs = tuple(
        ChunkDocumentRef(
            document_id=document_id,
            source_version_id=f"benchmark_source_{data.name}",
            parse_revision_id=f"benchmark_parse_{data.name}",
            chunk_revision_id=f"benchmark_revision_{data.name}",
            path=f"documents/{canonical_sha256(document_id)[:24]}.json",
            sha256="0" * 64,
            chunk_count=count,
        )
        for document_id, count in sorted(counts.items())
    )
    collection_id = f"benchmark_{data.name}_{canonical_sha256([data.source, len(chunks)])[:24]}"
    manifest = ChunkCollection(
        collection_id=collection_id,
        chunk_config=config,
        chunk_config_sha256=config.sha256,
        documents=document_refs,
        document_count=len(document_refs),
        chunk_count=len(chunks),
    )
    return LoadedChunkCollection(
        root=Path("."),
        manifest_path=Path("<in-memory-benchmark>"),
        manifest_sha256=hashlib.sha256(
            json.dumps(manifest.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest(),
        manifest=manifest,
        documents=(),
        chunks=tuple(chunks),
        document_names=MappingProxyType(document_names),
    )


def _deduplicated_documents(
    ranking: Sequence[str], chunk_to_document: Mapping[str, str]
) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for chunk_id in ranking:
        document_id = chunk_to_document[chunk_id]
        if document_id not in seen:
            seen.add(document_id)
            output.append(document_id)
    return output


def _ranking_metrics(
    cases: Sequence[BenchmarkCase], rankings: Mapping[str, Sequence[str]]
) -> dict[str, float | int]:
    if not cases:
        return {"query_count": 0}
    cutoffs = (1, 5, 10, 20)
    hits = Counter()
    recall = Counter()
    reciprocal_ranks: list[float] = []
    ndcg_values: list[float] = []
    for case in cases:
        ranking = rankings.get(case.case_id, ())
        for cutoff in cutoffs:
            retrieved = set(ranking[:cutoff])
            matched = retrieved & case.relevant_document_ids
            hits[cutoff] += int(bool(matched))
            recall[cutoff] += len(matched) / len(case.relevant_document_ids)
        ranks = [
            index + 1
            for index, document_id in enumerate(ranking[:10])
            if document_id in case.relevant_document_ids
        ]
        reciprocal_ranks.append(1.0 / min(ranks) if ranks else 0.0)
        dcg = sum(1.0 / math.log2(rank + 1) for rank in ranks)
        ideal_count = min(len(case.relevant_document_ids), 10)
        ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
        ndcg_values.append(dcg / ideal if ideal else 0.0)
    count = len(cases)
    output: dict[str, float | int] = {"query_count": count}
    for cutoff in cutoffs:
        output[f"hit_rate@{cutoff}"] = hits[cutoff] / count
        output[f"recall@{cutoff}"] = recall[cutoff] / count
    output["mrr@10"] = statistics.fmean(reciprocal_ranks)
    output["ndcg@10"] = statistics.fmean(ndcg_values)
    return output


def _select_cases(cases: Sequence[BenchmarkCase], maximum: int) -> tuple[BenchmarkCase, ...]:
    if maximum <= 0 or maximum >= len(cases):
        return tuple(cases)
    groups: dict[str, list[BenchmarkCase]] = defaultdict(list)
    for case in cases:
        primary = case.tags[0] if case.tags else "all"
        groups[primary].append(case)
    selected: list[BenchmarkCase] = []
    group_names = sorted(groups)
    while len(selected) < maximum and groups:
        for name in group_names:
            values = groups.get(name)
            if values:
                selected.append(values.pop(0))
                if len(selected) == maximum:
                    break
            if not values:
                groups.pop(name, None)
        group_names = [name for name in group_names if name in groups]
    return tuple(selected)


def evaluate_benchmark(
    data: BenchmarkData,
    output_root: Path,
    *,
    max_queries: int = 0,
    use_reranker: bool = True,
) -> tuple[Path, dict[str, Any]]:
    """Build the index, call RetrievalService, and persist layered metrics."""

    cases = _select_cases(data.cases, max_queries)
    collection = build_benchmark_collection(data)
    embedding = HashingEmbeddingProvider()
    index = CachedReferenceIndex()
    started = time.perf_counter()
    generation = IndexingService(collection, index, embedding).build().generation
    indexing_seconds = time.perf_counter() - started
    config = RetrievalConfig(
        dense_limit=20,
        bm25_body_limit=20,
        bm25_heading_limit=20,
        rrf_limit=30,
        rerank_limit=20,
        final_limit=10,
        section_window=0,
    )
    service = RetrievalService(
        collection,
        index,
        embedding,
        LexicalOverlapReranker() if use_reranker else None,
        config,
    )
    chunk_to_document = {chunk.chunk_id: chunk.document_id for chunk in collection.chunks}
    layer_rankings: dict[str, dict[str, list[str]]] = defaultdict(dict)
    latencies: list[float] = []
    results: list[dict[str, Any]] = []
    degraded = Counter()
    for position, case in enumerate(cases, 1):
        query_started = time.perf_counter()
        response = service.search(case.query)
        latencies.append(time.perf_counter() - query_started)
        rankings = {
            layer: _deduplicated_documents(ranking, chunk_to_document)
            for layer, ranking in response.trace.rankings.items()
        }
        rankings["final"] = _deduplicated_documents(
            [hit.chunk_id for hit in response.hits], chunk_to_document
        )
        for layer, ranking in rankings.items():
            layer_rankings[layer][case.case_id] = ranking
        degraded.update(response.trace.degraded)
        results.append(
            {
                "case_id": case.case_id,
                "query": case.query,
                "tags": list(case.tags),
                "relevant_document_ids": sorted(case.relevant_document_ids),
                "rankings": rankings,
            }
        )
        if position % 100 == 0:
            print(f"evaluated_queries={position}/{len(cases)}", file=sys.stderr)

    corpus_documents = {part.document_id for part in data.parts}
    gold_documents = {value for case in cases for value in case.relevant_document_ids}
    metrics = {
        layer: _ranking_metrics(cases, rankings)
        for layer, rankings in layer_rankings.items()
    }
    tag_metrics = {
        tag: _ranking_metrics(
            [case for case in cases if tag in case.tags], layer_rankings["final"]
        )
        for tag in sorted({tag for case in cases for tag in case.tags})
        if tag != "dev" and tag != "test" and tag != "gold-paragraph"
    }
    sorted_latencies = sorted(latencies)
    p95_index = min(len(sorted_latencies) - 1, math.ceil(len(sorted_latencies) * 0.95) - 1)
    summary: dict[str, Any] = {
        "schema_version": "esa-external-retrieval-evaluation-0.1",
        "dataset": data.name,
        "scope": data.scope,
        "source": dict(data.source),
        "backend": "ESA RetrievalService + cached reference hashing/BM25",
        "semantic_model": False,
        "reranker": "lexical-overlap" if use_reranker else "disabled",
        "index_generation_id": generation.index_generation_id,
        "document_count": len(corpus_documents),
        "chunk_count": len(collection.chunks),
        "query_count_available": len(data.cases),
        "query_count_evaluated": len(cases),
        "gold_document_coverage": len(gold_documents & corpus_documents) / len(gold_documents),
        "indexing_seconds": indexing_seconds,
        "query_latency_seconds": {
            "mean": statistics.fmean(latencies),
            "p50": statistics.median(latencies),
            "p95": sorted_latencies[p95_index],
        },
        "degraded": dict(degraded),
        "metrics": metrics,
        "tag_metrics_final": tag_metrics,
    }
    reranker_suffix = "lexical_reranker" if use_reranker else "no_reranker"
    run_name = f"{data.name}_reference_{len(cases)}q_{reranker_suffix}"
    output = output_root / run_name
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with (output / "results.jsonl").open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return output, summary


def _load_dataset(arguments: argparse.Namespace) -> BenchmarkData:
    if arguments.dataset == "scifact":
        return load_scifact(arguments.data_root / "beir/scifact")
    if arguments.dataset == "xor-tydi":
        return load_xor_tydi_gold(arguments.data_root / "xor_tydi")
    root = arguments.data_root / "m3docvqa"
    return load_m3docvqa(root, root / "extracted_pages.jsonl", arguments.workers)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run external datasets through ESA RAG")
    parser.add_argument("dataset", choices=("scifact", "xor-tydi", "m3docvqa"))
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--max-queries", type=int, default=0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--no-reranker", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.max_queries < 0 or arguments.workers <= 0:
        raise ValueError("max-queries must be non-negative and workers must be positive")
    data = _load_dataset(arguments)
    output, summary = evaluate_benchmark(
        data,
        arguments.output_root,
        max_queries=arguments.max_queries,
        use_reranker=not arguments.no_reranker,
    )
    print(f"result_dir={output}")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
