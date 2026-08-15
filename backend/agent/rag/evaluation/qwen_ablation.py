# backend/agent/rag/evaluation/qwen_ablation.py

"""Run the full real-Qwen retrieval ablation on the external benchmarks.

This module is intentionally evaluation-only.  It keeps the four principal
pipelines on the original query and evaluates QueryProcessor expansion as a
separate XOR-TyDi ablation, so query rewriting cannot leak into the component
comparison.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..indexes.reference import reference_tokens
from ..paths import workspace_root
from ..retrieval.query import RuleBasedQueryProcessor
from .external_benchmarks import (
    BenchmarkCase,
    BenchmarkData,
    build_benchmark_collection,
    load_m3docvqa,
    load_scifact,
    load_xor_tydi_gold,
)


DATASETS = ("scifact", "xor-tydi", "m3docvqa")
PIPELINES = ("bm25", "qwen_dense", "hybrid_rrf", "hybrid_qwen_reranker")
EMBEDDING_MODEL = Path(
    os.environ.get("RAG_EMBEDDING_MODEL_PATH", "Qwen/Qwen3-Embedding-4B")
)
RERANKER_MODEL = Path(
    os.environ.get("RAG_RERANKER_MODEL_PATH", "Qwen/Qwen3-Reranker-4B")
)
_BENCHMARK_ROOT = workspace_root() / "artifacts/rag/benchmarks"
DEFAULT_DATA_ROOT = _BENCHMARK_ROOT / "datasets"
DEFAULT_OUTPUT_ROOT = _BENCHMARK_ROOT / "qwen-ablation-20260809"
QUERY_INSTRUCTION = (
    "Given a web search query, retrieve relevant passages that answer the query"
)
TASK_RERANK_INSTRUCTIONS = {
    "scifact": (
        "Given a scientific claim, judge whether the document contains evidence "
        "that supports or refutes the claim."
    ),
    "xor-tydi": (
        "Given a question in any language, judge whether the English document "
        "contains evidence that answers the question."
    ),
    "m3docvqa": (
        "Judge whether the candidate document passage contains supporting evidence "
        "needed to answer the document question."
    ),
}


@dataclass(frozen=True)
class Ranking:
    """封装 `Ranking` 的状态与行为。"""
    document_ids: tuple[str, ...]
    chunk_ids: tuple[str, ...]


def _revision(model_root: Path) -> str | None:
    """处理 `_revision` 相关逻辑。"""
    path = model_root / "REVISION"
    return path.read_text(encoding="utf-8").strip() if path.is_file() else None


def _load_dataset(name: str, data_root: Path) -> BenchmarkData:
    """加载 `dataset` 相关数据。"""
    if name == "scifact":
        return load_scifact(data_root / "beir/scifact")
    if name == "xor-tydi":
        return load_xor_tydi_gold(data_root / "xor_tydi")
    root = data_root / "m3docvqa"
    return load_m3docvqa(root, root / "extracted_pages.jsonl")


def _selected_cases(
    cases: Sequence[BenchmarkCase], maximum: int
) -> tuple[BenchmarkCase, ...]:
    """处理 `_selected_cases` 相关逻辑。"""
    if maximum <= 0 or maximum >= len(cases):
        return tuple(cases)
    return tuple(cases[:maximum])


def _fingerprint(data: BenchmarkData, chunk_ids: Sequence[str]) -> str:
    """处理 `_fingerprint` 相关逻辑。"""
    digest = hashlib.sha256()
    digest.update(data.name.encode())
    digest.update(json.dumps(data.source, sort_keys=True).encode())
    digest.update(str(len(data.cases)).encode())
    for value in chunk_ids:
        digest.update(value.encode())
        digest.update(b"\0")
    return digest.hexdigest()


class _QwenEmbedder:
    """封装 `_QwenEmbedder` 的状态与行为。"""
    def __init__(self, model_root: Path, max_length: int) -> None:
        """初始化 `_QwenEmbedder` 实例。"""
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.torch = torch
        self.max_length = max_length
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_root, padding_side="left", local_files_only=True
        )
        self.model = (
            AutoModel.from_pretrained(
                model_root,
                torch_dtype=torch.bfloat16,
                attn_implementation="sdpa",
                local_files_only=True,
            )
            .to("cuda")
            .eval()
        )
        self.dimension = int(self.model.config.hidden_size)

    def encode(
        self, texts: Sequence[str], *, query: bool = False
    ) -> np.ndarray:
        """编码 `encode` 相关数据。

        Args:
            texts: Sequence[str] => `texts` 参数。
            query: bool => 查询文本。

        Returns:
            np.ndarray => 处理结果。
        """
        values = (
            [f"Instruct: {QUERY_INSTRUCTION}\nQuery: {text}" for text in texts]
            if query
            else list(texts)
        )
        encoded = self.tokenizer(
            values,
            padding=True,
            truncation=True,
            max_length=self.max_length,
            return_tensors="pt",
        )
        encoded = {name: value.to("cuda") for name, value in encoded.items()}
        with self.torch.inference_mode():
            hidden = self.model(**encoded).last_hidden_state
            pooled = self.torch.nn.functional.normalize(hidden[:, -1], p=2, dim=1)
        return pooled.float().cpu().numpy()


def _embedding_cache(
    output: Path,
    data: BenchmarkData,
    chunk_ids: Sequence[str],
    texts: Sequence[str],
    cases: Sequence[BenchmarkCase],
    *,
    document_batch_size: int,
    query_batch_size: int,
    max_length: int,
) -> tuple[Path, Path, dict[str, Any]]:
    """处理 `_embedding_cache` 相关逻辑。"""
    cache = output / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    document_path = cache / "document_embeddings.float16.npy"
    query_path = cache / "query_embeddings.float16.npy"
    metadata_path = cache / "embedding_metadata.json"
    expected = {
        "dataset_fingerprint": _fingerprint(data, chunk_ids),
        "embedding_model": str(EMBEDDING_MODEL),
        "embedding_revision": _revision(EMBEDDING_MODEL),
        "document_count": len(texts),
        "query_count": len(cases),
        "dimension": 2560,
        "max_length": max_length,
        "pooling": "last-token-l2-normalized",
        "query_instruction": QUERY_INSTRUCTION,
    }
    existing = None
    if metadata_path.is_file():
        existing = json.loads(metadata_path.read_text(encoding="utf-8"))
    documents_ready = document_path.is_file() and existing == expected
    queries_ready = query_path.is_file() and existing == expected
    if documents_ready and queries_ready:
        return document_path, query_path, expected

    embedder = _QwenEmbedder(EMBEDDING_MODEL, max_length)
    if embedder.dimension != expected["dimension"]:
        raise ValueError("unexpected Qwen embedding dimension")
    if not documents_ready:
        matrix = np.lib.format.open_memmap(
            document_path,
            mode="w+",
            dtype=np.float16,
            shape=(len(texts), embedder.dimension),
        )
        started = time.perf_counter()
        for start in range(0, len(texts), document_batch_size):
            stop = min(start + document_batch_size, len(texts))
            matrix[start:stop] = embedder.encode(texts[start:stop]).astype(np.float16)
            if stop % 1000 < document_batch_size or stop == len(texts):
                elapsed = time.perf_counter() - started
                print(
                    f"embedded_documents={stop}/{len(texts)} elapsed={elapsed:.1f}s",
                    flush=True,
                )
        matrix.flush()
        del matrix
    if not queries_ready:
        matrix = np.lib.format.open_memmap(
            query_path,
            mode="w+",
            dtype=np.float16,
            shape=(len(cases), embedder.dimension),
        )
        for start in range(0, len(cases), query_batch_size):
            stop = min(start + query_batch_size, len(cases))
            matrix[start:stop] = embedder.encode(
                [case.query for case in cases[start:stop]], query=True
            ).astype(np.float16)
        matrix.flush()
        del matrix
    metadata_path.write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    del embedder
    gc.collect()
    import torch

    torch.cuda.empty_cache()
    return document_path, query_path, expected


def _dense_rankings(
    document_embeddings: Path,
    query_embeddings: Path,
    chunk_document_indexes: np.ndarray,
    document_ids: Sequence[str],
    chunk_ids: Sequence[str],
    chunks_by_document: Sequence[np.ndarray],
    depth: int,
    batch_size: int,
) -> list[Ranking]:
    """处理 `_dense_rankings` 相关逻辑。"""
    import torch

    document_vectors = np.load(document_embeddings, mmap_mode="r")
    query_vectors = np.load(query_embeddings, mmap_mode="r")
    device_documents = torch.tensor(
        np.asarray(document_vectors), device="cuda", dtype=torch.bfloat16
    )
    device_document_indexes = torch.from_numpy(chunk_document_indexes).to(
        "cuda", dtype=torch.long
    )
    output: list[Ranking] = []
    selected_depth = min(depth, len(document_ids))
    for start in range(0, len(query_vectors), batch_size):
        stop = min(start + batch_size, len(query_vectors))
        queries = torch.tensor(
            np.asarray(query_vectors[start:stop]),
            device="cuda",
            dtype=torch.bfloat16,
        )
        with torch.inference_mode():
            scores = queries @ device_documents.T
            document_scores = torch.full(
                (stop - start, len(document_ids)),
                -torch.inf,
                device="cuda",
                dtype=scores.dtype,
            )
            document_scores.scatter_reduce_(
                1,
                device_document_indexes.expand(stop - start, -1),
                scores,
                reduce="amax",
                include_self=True,
            )
            top_scores, top_indexes = torch.topk(
                document_scores, selected_depth, dim=1
            )
        score_rows = scores.float().cpu().numpy()
        top_value_rows = top_scores.float().cpu().numpy()
        top_index_rows = top_indexes.cpu().numpy()
        for row, (values, indexes) in enumerate(zip(top_value_rows, top_index_rows)):
            ordered = sorted(
                zip(values.tolist(), indexes.tolist()),
                key=lambda pair: (-pair[0], document_ids[pair[1]]),
            )
            ranked_documents: list[str] = []
            representative_chunks: list[str] = []
            for _value, document_index in ordered:
                candidates = chunks_by_document[document_index]
                local = int(np.argmax(score_rows[row, candidates]))
                chunk_index = int(candidates[local])
                ranked_documents.append(document_ids[document_index])
                representative_chunks.append(chunk_ids[chunk_index])
            output.append(Ranking(tuple(ranked_documents), tuple(representative_chunks)))
        print(f"dense_queries={stop}/{len(query_vectors)}", flush=True)
        del queries, scores, document_scores, top_scores, top_indexes
    del device_documents, device_document_indexes
    torch.cuda.empty_cache()
    return output


class _Bm25:
    """封装 `_Bm25` 的状态与行为。"""
    def __init__(self, texts: Sequence[str], chunk_document_indexes: np.ndarray) -> None:
        """初始化 `_Bm25` 实例。"""
        self.chunk_document_indexes = chunk_document_indexes
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.lengths = np.zeros(len(texts), dtype=np.int32)
        for chunk_index, text in enumerate(texts):
            counts = Counter(reference_tokens(text))
            self.lengths[chunk_index] = sum(counts.values())
            for token, count in counts.items():
                self.postings[token].append((chunk_index, count))
            if (chunk_index + 1) % 10000 == 0:
                print(f"bm25_indexed_chunks={chunk_index + 1}/{len(texts)}", flush=True)
        self.average_length = float(self.lengths.mean()) if len(self.lengths) else 0.0

    def rank(
        self,
        query: str,
        document_ids: Sequence[str],
        chunk_ids: Sequence[str],
        depth: int,
    ) -> Ranking:
        """处理 `rank` 相关逻辑。

        Args:
            query: str => 查询文本。
            document_ids: Sequence[str] => `document_ids` 参数。
            chunk_ids: Sequence[str] => `chunk_ids` 参数。
            depth: int => `depth` 参数。

        Returns:
            Ranking => 处理结果。
        """
        query_counts = Counter(reference_tokens(query))
        chunk_scores: dict[int, float] = defaultdict(float)
        chunk_count = len(self.lengths)
        for token, query_frequency in query_counts.items():
            posting = self.postings.get(token, ())
            document_frequency = len(posting)
            if not document_frequency:
                continue
            inverse_document_frequency = math.log(
                1.0
                + (chunk_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            for chunk_index, frequency in posting:
                normalization = frequency + 1.2 * (
                    0.25
                    + 0.75
                    * float(self.lengths[chunk_index])
                    / (self.average_length or 1.0)
                )
                chunk_scores[chunk_index] += (
                    query_frequency
                    * inverse_document_frequency
                    * frequency
                    * 2.2
                    / normalization
                )
        best: dict[int, tuple[float, int]] = {}
        for chunk_index, score in chunk_scores.items():
            document_index = int(self.chunk_document_indexes[chunk_index])
            previous = best.get(document_index)
            if previous is None or score > previous[0] or (
                score == previous[0] and chunk_ids[chunk_index] < chunk_ids[previous[1]]
            ):
                best[document_index] = (score, chunk_index)
        ordered = sorted(
            best.items(),
            key=lambda item: (-item[1][0], document_ids[item[0]]),
        )[:depth]
        return Ranking(
            tuple(document_ids[index] for index, _value in ordered),
            tuple(chunk_ids[value[1]] for _index, value in ordered),
        )


def _rrf(left: Ranking, right: Ranking, depth: int, k: int) -> Ranking:
    """处理 `_rrf` 相关逻辑。"""
    scores: dict[str, float] = defaultdict(float)
    representatives: dict[str, tuple[float, str]] = {}
    for ranking in (left, right):
        for rank, (document_id, chunk_id) in enumerate(
            zip(ranking.document_ids, ranking.chunk_ids), 1
        ):
            contribution = 1.0 / (k + rank)
            scores[document_id] += contribution
            previous = representatives.get(document_id)
            if previous is None or contribution > previous[0] or (
                contribution == previous[0] and chunk_id < previous[1]
            ):
                representatives[document_id] = (contribution, chunk_id)
    ordered = sorted(scores, key=lambda value: (-scores[value], value))[:depth]
    return Ranking(
        tuple(ordered), tuple(representatives[value][1] for value in ordered)
    )


def _metrics(
    cases: Sequence[BenchmarkCase], rankings: Sequence[Sequence[str]]
) -> dict[str, float | int]:
    """处理 `_metrics` 相关逻辑。"""
    if not cases or len(cases) != len(rankings):
        raise ValueError("cases and rankings must be non-empty and aligned")
    hits = Counter()
    recalls = Counter()
    reciprocal_ranks: list[float] = []
    ndcg_values: list[float] = []
    full_coverage_20 = 0
    for case, ranking in zip(cases, rankings):
        for cutoff in (1, 5, 10, 20):
            matched = set(ranking[:cutoff]) & case.relevant_document_ids
            hits[cutoff] += int(bool(matched))
            recalls[cutoff] += len(matched) / len(case.relevant_document_ids)
        full_coverage_20 += int(
            case.relevant_document_ids.issubset(set(ranking[:20]))
        )
        relevant_ranks = [
            rank
            for rank, document_id in enumerate(ranking[:10], 1)
            if document_id in case.relevant_document_ids
        ]
        reciprocal_ranks.append(1.0 / min(relevant_ranks) if relevant_ranks else 0.0)
        dcg = sum(1.0 / math.log2(rank + 1) for rank in relevant_ranks)
        ideal = sum(
            1.0 / math.log2(rank + 1)
            for rank in range(1, min(10, len(case.relevant_document_ids)) + 1)
        )
        ndcg_values.append(dcg / ideal if ideal else 0.0)
    count = len(cases)
    result: dict[str, float | int] = {"query_count": count}
    for cutoff in (1, 5, 10, 20):
        result[f"hit@{cutoff}"] = hits[cutoff] / count
        result[f"evidence_coverage@{cutoff}"] = recalls[cutoff] / count
    result["mrr@10"] = statistics.fmean(reciprocal_ranks)
    result["ndcg@10"] = statistics.fmean(ndcg_values)
    result["full_evidence_coverage@20"] = full_coverage_20 / count
    return result


def retrieve(arguments: argparse.Namespace) -> None:
    """检索 `retrieve` 相关数据。

    Args:
        arguments: argparse.Namespace => `arguments` 参数。
    """
    data = _load_dataset(arguments.dataset, arguments.data_root)
    cases = _selected_cases(data.cases, arguments.max_queries)
    collection = build_benchmark_collection(data)
    output = arguments.output_root / arguments.dataset
    output.mkdir(parents=True, exist_ok=True)
    chunks = collection.chunks
    chunk_ids = [chunk.chunk_id for chunk in chunks]
    texts = [chunk.dense_text for chunk in chunks]
    document_ids = sorted({chunk.document_id for chunk in chunks})
    document_indexes = {value: index for index, value in enumerate(document_ids)}
    chunk_document_indexes = np.asarray(
        [document_indexes[chunk.document_id] for chunk in chunks], dtype=np.int64
    )
    grouped: list[list[int]] = [[] for _value in document_ids]
    for chunk_index, document_index in enumerate(chunk_document_indexes):
        grouped[int(document_index)].append(chunk_index)
    chunks_by_document = [np.asarray(value, dtype=np.int64) for value in grouped]

    document_path, query_path, embedding_metadata = _embedding_cache(
        output,
        data,
        chunk_ids,
        texts,
        cases,
        document_batch_size=arguments.embedding_batch_size,
        query_batch_size=arguments.query_batch_size,
        max_length=arguments.embedding_max_length,
    )
    dense = _dense_rankings(
        document_path,
        query_path,
        chunk_document_indexes,
        document_ids,
        chunk_ids,
        chunks_by_document,
        arguments.retrieval_depth,
        arguments.dense_search_batch_size,
    )
    bm25_backend = _Bm25(texts, chunk_document_indexes)
    query_processor = RuleBasedQueryProcessor()
    bm25_original: list[Ranking] = []
    bm25_expanded: list[Ranking] = []
    expansion_changed = 0
    original_cache: dict[str, Ranking] = {}
    expanded_cache: dict[str, Ranking] = {}
    for index, case in enumerate(cases, 1):
        original = original_cache.get(case.query)
        if original is None:
            original = bm25_backend.rank(
                case.query, document_ids, chunk_ids, arguments.retrieval_depth
            )
            original_cache[case.query] = original
        bm25_original.append(original)
        if arguments.dataset == "xor-tydi":
            expanded_query = query_processor.process(case.query).bm25_body_query
            expansion_changed += int(expanded_query != case.query)
            expanded = expanded_cache.get(expanded_query)
            if expanded is None:
                expanded = bm25_backend.rank(
                    expanded_query,
                    document_ids,
                    chunk_ids,
                    arguments.retrieval_depth,
                )
                expanded_cache[expanded_query] = expanded
            bm25_expanded.append(expanded)
        if index % 100 == 0 or index == len(cases):
            print(f"bm25_queries={index}/{len(cases)}", flush=True)

    hybrid = [
        _rrf(bm25, semantic, arguments.rerank_depth, arguments.rrf_k)
        for bm25, semantic in zip(bm25_original, dense)
    ]
    expanded_hybrid = (
        [
            _rrf(bm25, semantic, arguments.rerank_depth, arguments.rrf_k)
            for bm25, semantic in zip(bm25_expanded, dense)
        ]
        if bm25_expanded
        else []
    )
    result_path = output / "retrieval.jsonl"
    with result_path.open("w", encoding="utf-8") as handle:
        for case_index, case in enumerate(cases):
            rankings = {
                "bm25": list(bm25_original[case_index].document_ids),
                "qwen_dense": list(dense[case_index].document_ids),
                "hybrid_rrf": list(hybrid[case_index].document_ids),
            }
            if expanded_hybrid:
                rankings["hybrid_rrf_query_processor"] = list(
                    expanded_hybrid[case_index].document_ids
                )
            handle.write(
                json.dumps(
                    {
                        "case_index": case_index,
                        "case_id": case.case_id,
                        "query": case.query,
                        "tags": list(case.tags),
                        "relevant_document_ids": sorted(case.relevant_document_ids),
                        "rankings": rankings,
                        "hybrid_candidate_chunk_ids": list(
                            hybrid[case_index].chunk_ids
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
    metrics = {
        "bm25": _metrics(cases, [value.document_ids for value in bm25_original]),
        "qwen_dense": _metrics(cases, [value.document_ids for value in dense]),
        "hybrid_rrf": _metrics(cases, [value.document_ids for value in hybrid]),
    }
    xor_ablation = None
    if expanded_hybrid:
        xor_ablation = {
            "qwen_dense_original_query": metrics["qwen_dense"],
            "qwen_dense_plus_bm25_original": metrics["hybrid_rrf"],
            "qwen_dense_plus_bm25_query_processor": _metrics(
                cases, [value.document_ids for value in expanded_hybrid]
            ),
            "query_processor_changed_query_count": expansion_changed,
        }
    summary = {
        "schema_version": "esa-qwen-ablation-1.0",
        "status": "retrieval_complete",
        "dataset": data.name,
        "scope": data.scope,
        "source": dict(data.source),
        "query_count_available": len(data.cases),
        "query_count_evaluated": len(cases),
        "document_count": len(document_ids),
        "chunk_count": len(chunks),
        "embedding": embedding_metadata,
        "bm25": {
            "text": "chunk dense_text (title plus body where title exists)",
            "formula": "BM25 k1=1.2 b=0.75; document score=max chunk score",
            "tokenizer": "ESA reference multilingual-lite tokenizer 0.1",
            "query": "original query",
        },
        "fusion": {
            "method": "document-level reciprocal rank fusion",
            "rrf_k": arguments.rrf_k,
            "input_depth": arguments.retrieval_depth,
            "output_depth": arguments.rerank_depth,
        },
        "metrics": metrics,
        "xor_query_processor_ablation": xor_ablation,
        "evidence_coverage_definition": (
            "macro-average fraction of gold supporting documents retrieved at k"
        ),
        "result_file": str(result_path),
    }
    (output / "retrieval_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


class _QwenReranker:
    """封装 `_QwenReranker` 的状态与行为。"""
    def __init__(self, model_root: Path, max_length: int) -> None:
        """初始化 `_QwenReranker` 实例。"""
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.max_length = max_length
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_root, padding_side="left", local_files_only=True
        )
        self.model = (
            AutoModelForCausalLM.from_pretrained(
                model_root,
                torch_dtype=torch.bfloat16,
                attn_implementation="sdpa",
                local_files_only=True,
            )
            .to("cuda")
            .eval()
        )
        self.false_id = self.tokenizer.convert_tokens_to_ids("no")
        self.true_id = self.tokenizer.convert_tokens_to_ids("yes")
        prefix = (
            "<|im_start|>system\nJudge whether the Document meets the requirements "
            "based on the Query and the Instruct provided. Note that the answer can "
            'only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
        )
        suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        self.prefix_ids = self.tokenizer.encode(prefix, add_special_tokens=False)
        self.suffix_ids = self.tokenizer.encode(suffix, add_special_tokens=False)

    def score(
        self,
        query: str,
        documents: Sequence[str],
        instruction: str = QUERY_INSTRUCTION,
    ) -> list[float]:
        """处理 `score` 相关逻辑。

        Args:
            query: str => 查询文本。
            documents: Sequence[str] => `documents` 参数。
            instruction: str => `instruction` 参数。

        Returns:
            list[float] => 处理结果。
        """
        texts = [
            f"<Instruct>: {instruction}\n<Query>: {query}\n<Document>: {value}"
            for value in documents
        ]
        values = self.tokenizer(
            texts,
            padding=False,
            truncation=True,
            max_length=self.max_length - len(self.prefix_ids) - len(self.suffix_ids),
        )
        values["input_ids"] = [
            self.prefix_ids + ids + self.suffix_ids for ids in values["input_ids"]
        ]
        values = self.tokenizer.pad(values, padding=True, return_tensors="pt")
        values = {name: value.to("cuda") for name, value in values.items()}
        with self.torch.inference_mode():
            logits = self.model(**values).logits[:, -1, :]
            binary = self.torch.stack(
                [logits[:, self.false_id], logits[:, self.true_id]], dim=1
            )
            scores = self.torch.nn.functional.softmax(binary, dim=1)[:, 1]
        return scores.float().cpu().tolist()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 `jsonl` 相关数据。"""
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def rerank(arguments: argparse.Namespace) -> None:
    """处理 `rerank` 相关逻辑。

    Args:
        arguments: argparse.Namespace => `arguments` 参数。
    """
    data = _load_dataset(arguments.dataset, arguments.data_root)
    cases = _selected_cases(data.cases, arguments.max_queries)
    collection = build_benchmark_collection(data)
    chunks = {chunk.chunk_id: chunk for chunk in collection.chunks}
    output = arguments.output_root / arguments.dataset
    retrieval_path = output / "retrieval.jsonl"
    records = _read_jsonl(retrieval_path)
    if len(records) != len(cases):
        raise ValueError("retrieval record count does not match selected cases")
    partial_path = output / "reranker.partial.jsonl"
    completed: dict[int, dict[str, Any]] = {}
    if partial_path.is_file():
        for value in _read_jsonl(partial_path):
            completed[int(value["case_index"])] = value
    reranker = _QwenReranker(RERANKER_MODEL, arguments.reranker_max_length)
    mode = "a" if partial_path.is_file() else "w"
    with partial_path.open(mode, encoding="utf-8") as handle:
        for index, (case, record) in enumerate(zip(cases, records)):
            if index in completed:
                continue
            document_ids = record["rankings"]["hybrid_rrf"]
            chunk_ids = record["hybrid_candidate_chunk_ids"]
            documents = [chunks[value].dense_text for value in chunk_ids]
            scores: list[float] = []
            for start in range(0, len(documents), arguments.reranker_batch_size):
                scores.extend(
                    reranker.score(
                        case.query,
                        documents[start : start + arguments.reranker_batch_size],
                    )
                )
            ordered = sorted(
                range(len(document_ids)),
                key=lambda value: (-scores[value], value),
            )
            result = {
                "case_index": index,
                "ranking": [document_ids[value] for value in ordered],
                "scores": [scores[value] for value in ordered],
            }
            handle.write(json.dumps(result, sort_keys=True) + "\n")
            handle.flush()
            completed[index] = result
            if (index + 1) % 25 == 0 or index + 1 == len(cases):
                print(f"reranked_queries={index + 1}/{len(cases)}", flush=True)
    ordered_completed = [completed[index] for index in range(len(cases))]
    rankings = [value["ranking"] for value in ordered_completed]
    metrics = _metrics(cases, rankings)
    final_path = output / "reranker.jsonl"
    with final_path.open("w", encoding="utf-8") as handle:
        for value in ordered_completed:
            handle.write(json.dumps(value, sort_keys=True) + "\n")
    retrieval_summary = json.loads(
        (output / "retrieval_summary.json").read_text(encoding="utf-8")
    )
    summary = {
        **retrieval_summary,
        "status": "complete",
        "reranker": {
            "model": str(RERANKER_MODEL),
            "revision": _revision(RERANKER_MODEL),
            "dtype": "bfloat16",
            "attention": "sdpa",
            "max_length": arguments.reranker_max_length,
            "batch_size": arguments.reranker_batch_size,
            "score": "normalized yes/no token probability",
            "candidate_source": "top-20 original-query hybrid RRF documents",
        },
        "metrics": {
            **retrieval_summary["metrics"],
            "hybrid_qwen_reranker": metrics,
        },
        "reranker_result_file": str(final_path),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


def report(arguments: argparse.Namespace) -> None:
    """处理 `report` 相关逻辑。

    Args:
        arguments: argparse.Namespace => `arguments` 参数。
    """
    summaries = {
        dataset: json.loads(
            (arguments.output_root / dataset / "summary.json").read_text(encoding="utf-8")
        )
        for dataset in DATASETS
    }
    report_value = {
        "schema_version": "esa-qwen-ablation-report-1.0",
        "datasets": summaries,
        "pipelines": {
            pipeline: {
                dataset: summaries[dataset]["metrics"][pipeline]
                for dataset in DATASETS
            }
            for pipeline in PIPELINES
        },
        "xor_query_processor_ablation": summaries["xor-tydi"][
            "xor_query_processor_ablation"
        ],
    }
    path = arguments.output_root / "report.json"
    path.write_text(
        json.dumps(report_value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"report={path}")
    print(json.dumps(report_value["pipelines"], ensure_ascii=False, indent=2))


def _parser() -> argparse.ArgumentParser:
    """处理 `_parser` 相关逻辑。"""
    parser = argparse.ArgumentParser(description="Run strict real-Qwen ablations")
    parser.add_argument("phase", choices=("retrieve", "rerank", "report"))
    parser.add_argument("dataset", nargs="?", choices=DATASETS)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--max-queries", type=int, default=0)
    parser.add_argument("--embedding-batch-size", type=int, default=16)
    parser.add_argument("--query-batch-size", type=int, default=64)
    parser.add_argument("--embedding-max-length", type=int, default=2048)
    parser.add_argument("--dense-search-batch-size", type=int, default=64)
    parser.add_argument("--retrieval-depth", type=int, default=100)
    parser.add_argument("--rerank-depth", type=int, default=20)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--reranker-batch-size", type=int, default=20)
    parser.add_argument("--reranker-max-length", type=int, default=1024)
    return parser


def main(argv: list[str] | None = None) -> int:
    """运行当前模块的命令行入口。

    Args:
        argv: list[str] | None => `argv` 参数。

    Returns:
        int => 处理结果。
    """
    arguments = _parser().parse_args(argv)
    if arguments.phase != "report" and arguments.dataset is None:
        raise ValueError("dataset is required for retrieve and rerank")
    if arguments.max_queries < 0:
        raise ValueError("max-queries cannot be negative")
    if arguments.phase == "retrieve":
        retrieve(arguments)
    elif arguments.phase == "rerank":
        rerank(arguments)
    else:
        report(arguments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
