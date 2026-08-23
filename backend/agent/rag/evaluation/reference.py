# backend/agent/rag/evaluation/reference.py

"""

这个文件干什么：在真实 ChunkCollection 上执行确定性分层检索评测。

直白点说就是：在真实 Chunk 集合上跑一套可重复的参考评测，并输出逐题结果和汇总报告。

在真实 ChunkCollection 上执行确定性分层检索评测。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from backend.core.utils.config import RAG_WORKSPACE_ROOT

from ..chunk import Chunk
from ..chunk.models import canonical_sha256
from ..chunk.serializer import file_sha256, save_json
from ..collection import LoadedChunkCollection, load_chunk_collection
from ..indexes import ReferenceIndex
from ..indexing import IndexGeneration, IndexingService
from ..inference import HashingEmbeddingProvider, LexicalOverlapReranker
from ..retrieval.contracts import RetrievalConfig, SearchResponse
from ..retrieval.service import RetrievalService
from .metrics import EvaluationCase, RetrievalMetrics, evaluate_layers

DEFAULT_MANIFEST = (
    RAG_WORKSPACE_ROOT
    / "artifacts/chunk/collections/collection_bc7a6054e159eb7346e94df0/manifest.json"
)
DEFAULT_CASES = RAG_WORKSPACE_ROOT / "data/evaluation/reference_evaluation_v1.json"
DEFAULT_OUTPUT = RAG_WORKSPACE_ROOT / "artifacts/rag/evaluations"


MetricPayload = dict[str, int | float]
LayerMetrics = dict[str, MetricPayload]
CategoryMetrics = dict[str, LayerMetrics]
RankingMap = dict[str, dict[str, Sequence[str]]]


class HitResult(TypedDict):
    """一个评测命中的可序列化结构。"""

    chunk_id: str
    retrieval_score: float
    rerank_score: float | None
    evidence_ids: list[str]
    quote_eligible_count: int
    context_chunk_ids: list[str]


class CaseResult(TypedDict):
    """一条问题的检索结果与 Gold 对照。"""

    case_id: str
    query: str
    answerable: bool
    category_tags: list[str]
    gold_chunk_ids: list[str]
    gold_evidence_ids: list[str]
    rankings: dict[str, list[str]]
    hits: list[HitResult]
    degraded: list[str]


class EvaluationSummary(TypedDict):
    """确定性参考评测摘要。"""

    schema_version: str
    evaluation_id: str
    index_generation_id: str
    collection_id: str
    document_count: int
    chunk_count: int
    evidence_count: int
    case_count: int
    positive_case_count: int
    negative_case_count: int
    gold_evidence_resolution_rate: float
    retrieved_gold_evidence_rate_at_final_5: float
    negative_top5_candidate_rate: float
    negative_max_reference_rerank_score: float
    negative_mean_reference_rerank_score: float
    metrics: LayerMetrics
    category_metrics: CategoryMetrics
    quality_gate: dict[str, bool]


@dataclass(frozen=True)
class _EvaluationRuntime:
    """一次参考评测共享的索引、服务与配置。"""

    service: RetrievalService
    generation: IndexGeneration
    config: RetrievalConfig
    reranker: LexicalOverlapReranker


def load_evaluation_cases(
    path: Path,
    collection: LoadedChunkCollection,
) -> tuple[EvaluationCase, ...]:
    """加载人工标注并验证每个 gold 都能回查到指定 Chunk/Evidence。"""

    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "rag-reference-evaluation-0.1":
        raise ValueError("unsupported evaluation schema")
    if raw.get("collection_id") != collection.manifest.collection_id:
        raise ValueError("evaluation collection_id does not match manifest")
    cases = tuple(
        EvaluationCase(
            case_id=item["case_id"],
            query=item["query"],
            answerable=item["answerable"],
            relevant_chunk_ids=frozenset(item["relevant_chunk_ids"]),
            relevant_evidence_ids=frozenset(item["relevant_evidence_ids"]),
            target_document_ids=frozenset(item["target_document_ids"]),
            category_tags=tuple(item["category_tags"]),
            annotation_note=item["annotation_note"],
        )
        for item in raw["cases"]
    )
    positives = _validate_case_counts(cases)
    chunks = {chunk.chunk_id: chunk for chunk in collection.chunks}
    for case in positives:
        _validate_positive_case(case, chunks)
    _validate_document_coverage(positives, collection)
    return cases


def _validate_case_counts(
    cases: Sequence[EvaluationCase],
) -> list[EvaluationCase]:
    """校验固定评测集的唯一性及正负例数量。"""

    if len(cases) != 42:
        raise ValueError("evaluation set must contain exactly 42 cases")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("evaluation case_id values must be unique")
    positives = [case for case in cases if case.answerable]
    if len(positives) != 35:
        raise ValueError("evaluation set must contain exactly 35 positive cases")
    if len(cases) - len(positives) != 7:
        raise ValueError("evaluation set must contain exactly 7 negative cases")
    return positives


def _validate_positive_case(
    case: EvaluationCase,
    chunks: Mapping[str, Chunk],
) -> None:
    """校验一条正例的 Chunk、文档和 Evidence Gold 引用。"""

    missing_chunks = case.relevant_chunk_ids - chunks.keys()
    if missing_chunks:
        raise ValueError(
            f"unknown gold chunks in {case.case_id}: {sorted(missing_chunks)}"
        )
    actual_documents = {
        chunks[chunk_id].document_id for chunk_id in case.relevant_chunk_ids
    }
    if actual_documents != set(case.target_document_ids):
        raise ValueError(f"gold document mismatch in {case.case_id}")
    available_evidence = {
        evidence.evidence_id
        for chunk_id in case.relevant_chunk_ids
        for evidence in chunks[chunk_id].evidence
    }
    missing_evidence = case.relevant_evidence_ids - available_evidence
    if missing_evidence:
        raise ValueError(
            f"unknown gold evidence in {case.case_id}: {sorted(missing_evidence)}"
        )


def _validate_document_coverage(
    positives: Sequence[EvaluationCase],
    collection: LoadedChunkCollection,
) -> None:
    """确保每份真实文档恰好有五条正例。"""

    counts = {
        document_id: sum(document_id in case.target_document_ids for case in positives)
        for document_id in collection.document_names
    }
    if set(counts.values()) != {5}:
        raise ValueError(f"every document needs five positive cases: {counts}")


def _metrics_dict(metrics: RetrievalMetrics) -> dict[str, int | float]:
    """处理 `_metrics_dict` 相关逻辑。"""
    return dataclasses.asdict(metrics)


def _layer_metrics(
    cases: Sequence[EvaluationCase],
    rankings: Mapping[str, Mapping[str, Sequence[str]]],
) -> LayerMetrics:
    """处理 `_layer_metrics` 相关逻辑。"""
    metrics = evaluate_layers(cases, lambda query: rankings[query])
    return {name: _metrics_dict(value) for name, value in metrics.items()}


def _category_metrics(
    cases: Sequence[EvaluationCase],
    rankings: Mapping[str, Mapping[str, Sequence[str]]],
) -> CategoryMetrics:
    """处理 `_category_metrics` 相关逻辑。"""
    tags = sorted(
        {tag for case in cases if case.answerable for tag in case.category_tags}
    )
    return {
        tag: _layer_metrics(
            [case for case in cases if case.answerable and tag in case.category_tags],
            rankings,
        )
        for tag in tags
    }


def run_reference_evaluation(
    manifest_path: Path = DEFAULT_MANIFEST,
    cases_path: Path = DEFAULT_CASES,
    output_root: Path = DEFAULT_OUTPUT,
) -> tuple[Path, EvaluationSummary]:
    """构建参考索引、执行 42 条评测并写入确定性产物。"""

    collection = load_chunk_collection(manifest_path)
    cases = load_evaluation_cases(cases_path, collection)
    runtime = _create_runtime(collection)
    evaluation_payload = _evaluation_payload(runtime, cases_path)
    evaluation_id = f"reference_eval_{canonical_sha256(evaluation_payload)[:24]}"
    evaluation_root = output_root / evaluation_id
    evaluation_root.mkdir(parents=True, exist_ok=True)

    case_results, rankings_by_query = _run_cases(runtime.service, cases)
    summary = _build_summary(
        evaluation_id,
        collection,
        cases,
        case_results,
        rankings_by_query,
        runtime.generation.index_generation_id,
    )
    _write_evaluation_artifacts(
        evaluation_root,
        evaluation_id,
        evaluation_payload,
        runtime,
        cases,
        case_results,
        summary,
    )
    return evaluation_root, summary


def _create_runtime(collection: LoadedChunkCollection) -> _EvaluationRuntime:
    """建立确定性索引与检索服务。"""

    config = RetrievalConfig(reranker_enabled=True)
    embedding = HashingEmbeddingProvider()
    reranker = LexicalOverlapReranker()
    index = ReferenceIndex()
    build_result = IndexingService(collection, index, embedding).build()
    service = RetrievalService(collection, index, embedding, reranker, config)
    return _EvaluationRuntime(
        service=service,
        generation=build_result.generation,
        config=config,
        reranker=reranker,
    )


def _evaluation_payload(
    runtime: _EvaluationRuntime,
    cases_path: Path,
) -> dict[str, object]:
    """构造决定评测运行身份的稳定配置。"""

    return {
        "schema_version": "reference-evaluation-run-0.2",
        "index_generation_id": runtime.generation.index_generation_id,
        "evaluation_set_sha256": file_sha256(cases_path),
        "reranker_fingerprint": runtime.reranker.configuration_fingerprint,
        "retrieval_config": dataclasses.asdict(runtime.config),
    }


def _run_cases(
    service: RetrievalService,
    cases: Sequence[EvaluationCase],
) -> tuple[list[CaseResult], RankingMap]:
    """执行全部问题并保留每一层排名。"""

    case_results: list[CaseResult] = []
    rankings_by_query: RankingMap = {}
    for case in cases:
        response = service.search(case.query)
        if response.trace.rankings.get("fusion"):
            if not response.trace.reranker_applied:
                raise AssertionError("reference evaluation reranker was not applied")
            if any(hit.rerank_score is None for hit in response.hits):
                raise AssertionError("reference evaluation hit lacks reranker score")
        rankings = {
            name: list(values) for name, values in response.trace.rankings.items()
        }
        rankings_by_query[case.query] = rankings
        case_results.append(_case_result(case, rankings, response))
    return case_results, rankings_by_query


def _case_result(
    case: EvaluationCase,
    rankings: dict[str, list[str]],
    response: SearchResponse,
) -> CaseResult:
    """把领域检索响应转换为评测 JSON 结构。"""

    return {
        "case_id": case.case_id,
        "query": case.query,
        "answerable": case.answerable,
        "category_tags": list(case.category_tags),
        "gold_chunk_ids": sorted(case.relevant_chunk_ids),
        "gold_evidence_ids": sorted(case.relevant_evidence_ids),
        "rankings": rankings,
        "hits": [
            {
                "chunk_id": hit.chunk_id,
                "retrieval_score": hit.retrieval_score,
                "rerank_score": hit.rerank_score,
                "evidence_ids": [item.evidence_id for item in hit.evidence],
                "quote_eligible_count": sum(
                    item.quote_eligible for item in hit.evidence
                ),
                "context_chunk_ids": list(hit.context_chunk_ids),
            }
            for hit in response.hits
        ],
        "degraded": list(response.trace.degraded),
    }


def _build_summary(
    evaluation_id: str,
    collection: LoadedChunkCollection,
    cases: Sequence[EvaluationCase],
    case_results: Sequence[CaseResult],
    rankings_by_query: RankingMap,
    index_generation_id: str,
) -> EvaluationSummary:
    """计算总体、分层、分类与负例诊断指标。"""

    positive = [case for case in cases if case.answerable]
    negative_results = [item for item in case_results if not item["answerable"]]
    retrieved_gold_evidence = 0
    for case, result in zip(cases, case_results):
        if not case.answerable:
            continue
        returned = {
            evidence_id for hit in result["hits"] for evidence_id in hit["evidence_ids"]
        }
        retrieved_gold_evidence += len(returned & case.relevant_evidence_ids)
    total_gold_evidence = sum(len(case.relevant_evidence_ids) for case in positive)
    negative_scores = [
        max((hit["rerank_score"] or 0.0 for hit in item["hits"]), default=0.0)
        for item in negative_results
    ]
    return {
        "schema_version": "reference-evaluation-summary-0.2",
        "evaluation_id": evaluation_id,
        "index_generation_id": index_generation_id,
        "collection_id": collection.manifest.collection_id,
        "document_count": len(collection.documents),
        "chunk_count": len(collection.chunks),
        "evidence_count": sum(len(chunk.evidence) for chunk in collection.chunks),
        "case_count": len(cases),
        "positive_case_count": len(positive),
        "negative_case_count": len(negative_results),
        "gold_evidence_resolution_rate": 1.0,
        "retrieved_gold_evidence_rate_at_final_5": (
            retrieved_gold_evidence / total_gold_evidence
            if total_gold_evidence
            else 0.0
        ),
        "negative_top5_candidate_rate": (
            sum(bool(item["hits"][:5]) for item in negative_results)
            / len(negative_results)
        ),
        "negative_max_reference_rerank_score": max(negative_scores, default=0.0),
        "negative_mean_reference_rerank_score": (
            sum(negative_scores) / len(negative_scores) if negative_scores else 0.0
        ),
        "metrics": _layer_metrics(cases, rankings_by_query),
        "category_metrics": _category_metrics(cases, rankings_by_query),
        "quality_gate": {
            "semantic_metric_threshold_applied": False,
            "answer_generation_performed": False,
            "citation_claims_generated": False,
        },
    }


def _write_evaluation_artifacts(
    evaluation_root: Path,
    evaluation_id: str,
    evaluation_payload: Mapping[str, object],
    runtime: _EvaluationRuntime,
    cases: Sequence[EvaluationCase],
    case_results: Sequence[CaseResult],
    summary: EvaluationSummary,
) -> None:
    """写入 manifest、逐题结果、摘要及内容哈希。"""

    manifest = {
        "schema_version": "reference-evaluation-manifest-0.2",
        "evaluation_id": evaluation_id,
        "index_generation_id": runtime.generation.index_generation_id,
        "index_generation": runtime.generation.to_dict(),
        "evaluation_set_sha256": evaluation_payload["evaluation_set_sha256"],
        "reranker_fingerprint": runtime.reranker.configuration_fingerprint,
        "retrieval_config": dataclasses.asdict(runtime.config),
        "case_count": len(cases),
        "output_files": ["results.json", "summary.json", "hashes.json"],
    }
    save_json(manifest, evaluation_root / "manifest.json")
    save_json({"cases": case_results}, evaluation_root / "results.json")
    save_json(summary, evaluation_root / "summary.json")
    hashes = {
        name: file_sha256(evaluation_root / name)
        for name in ("manifest.json", "results.json", "summary.json")
    }
    save_json(hashes, evaluation_root / "hashes.json")


def main(argv: Iterable[str] | None = None) -> int:
    """运行当前模块的命令行入口。

    Args:
        argv: Iterable[str] | None => `argv` 参数。

    Returns:
        int => 处理结果。
    """
    parser = argparse.ArgumentParser(
        description="执行真实 ChunkCollection 确定性参考评测"
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args(argv)
    root, summary = run_reference_evaluation(
        arguments.manifest, arguments.cases, arguments.output
    )
    print(f"evaluation_root={root}")
    print(
        f"documents={summary['document_count']} chunks={summary['chunk_count']} "
        f"cases={summary['case_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
