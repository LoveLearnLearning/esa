# backend/agent/rag/evaluation/fusion_ablation.py

"""Rebuild raw route scores and evaluate dense-dominant fusion offline.

This module deliberately reuses cached Qwen embeddings and the historical
top-100 dense ranking.  It never reloads the embedding model and records enough
per-candidate state to replay every fusion setting without Qdrant or a GPU.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..indexes.reference import reference_tokens
from ..paths import workspace_root
from ..retrieval.calibration import (
    CosineScoreCalibrator,
    IdentityScoreCalibrator,
    PercentileScoreCalibrator,
    RobustMinMaxScoreCalibrator,
    ScoreCalibrator,
)
from ..retrieval.contracts import RankedItem
from ..retrieval.fusion import (
    reciprocal_rank_fusion,
    score_level_weighted_fusion,
    weighted_reciprocal_rank_fusion,
)
from .external_benchmarks import BenchmarkCase, build_benchmark_collection
from .qwen_ablation import _load_dataset, _metrics, _read_jsonl, _selected_cases

_BENCHMARK_ROOT = workspace_root() / "artifacts/rag/benchmarks"
DEFAULT_DATA_ROOT = _BENCHMARK_ROOT / "datasets"
DEFAULT_INPUT_ROOT = _BENCHMARK_ROOT / "qwen-ablation-20260809"
DEFAULT_OUTPUT_ROOT = _BENCHMARK_ROOT / "weighted-fusion-20260811"
DATASETS = ("scifact", "xor-tydi", "m3docvqa")


@dataclass(frozen=True)
class RawRanking:
    """封装 `RawRanking` 的状态与行为。"""
    document_ids: tuple[str, ...]
    scores: tuple[float, ...]
    top_chunk_ids: tuple[tuple[str, ...], ...]

    def items(self) -> list[RankedItem]:
        """处理 `items` 相关逻辑。"""
        return [
            RankedItem(document_id, score)
            for document_id, score in zip(self.document_ids, self.scores)
        ]


@dataclass
class _FieldIndex:
    """封装 `_FieldIndex` 的状态与行为。"""
    postings: dict[str, list[tuple[int, int]]]
    lengths: np.ndarray
    average_length: float


class _RawBm25:
    """Evaluation-only BM25 that preserves document scores and top-3 chunks."""

    def __init__(
        self,
        texts: Sequence[str],
        chunk_document_indexes: np.ndarray,
        chunk_ids: Sequence[str],
    ) -> None:
        """初始化 `_RawBm25` 实例。"""
        postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        lengths = np.zeros(len(texts), dtype=np.int32)
        for chunk_index, text in enumerate(texts):
            counts = Counter(reference_tokens(text))
            lengths[chunk_index] = sum(counts.values())
            for token, count in counts.items():
                postings[token].append((chunk_index, count))
        self.field = _FieldIndex(
            dict(postings),
            lengths,
            float(lengths.mean()) if len(lengths) else 0.0,
        )
        self.chunk_document_indexes = chunk_document_indexes
        self.chunk_ids = chunk_ids

    def rank(self, query: str, document_ids: Sequence[str], depth: int) -> RawRanking:
        """处理 `rank` 相关逻辑。

        Args:
            query: str => 查询文本。
            document_ids: Sequence[str] => `document_ids` 参数。
            depth: int => `depth` 参数。

        Returns:
            RawRanking => 处理结果。
        """
        query_counts = Counter(reference_tokens(query))
        chunk_scores: dict[int, float] = defaultdict(float)
        chunk_count = len(self.field.lengths)
        for token, query_frequency in query_counts.items():
            posting = self.field.postings.get(token, ())
            document_frequency = len(posting)
            if not document_frequency:
                continue
            inverse_document_frequency = math.log(
                1.0
                + (chunk_count - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            for chunk_index, frequency in posting:
                normalization = frequency + 1.2 * (
                    0.25
                    + 0.75
                    * float(self.field.lengths[chunk_index])
                    / (self.field.average_length or 1.0)
                )
                chunk_scores[chunk_index] += (
                    query_frequency
                    * inverse_document_frequency
                    * frequency
                    * 2.2
                    / normalization
                )
        by_document: dict[int, list[tuple[float, int]]] = defaultdict(list)
        for chunk_index, score in chunk_scores.items():
            by_document[int(self.chunk_document_indexes[chunk_index])].append(
                (score, chunk_index)
            )
        ordered_documents = sorted(
            by_document,
            key=lambda index: (
                -max(value[0] for value in by_document[index]),
                document_ids[index],
            ),
        )[:depth]
        scores: list[float] = []
        top_chunks: list[tuple[str, ...]] = []
        for document_index in ordered_documents:
            chunks = sorted(
                by_document[document_index],
                key=lambda value: (-value[0], self.chunk_ids[value[1]]),
            )
            scores.append(chunks[0][0])
            top_chunks.append(
                tuple(self.chunk_ids[index] for _score, index in chunks[:3])
            )
        return RawRanking(
            tuple(document_ids[index] for index in ordered_documents),
            tuple(scores),
            tuple(top_chunks),
        )


def _dense_raw_rankings(
    historical: Sequence[dict[str, Any]],
    document_embeddings: Path,
    query_embeddings: Path,
    document_indexes: dict[str, int],
    chunks_by_document: Sequence[np.ndarray],
    chunk_ids: Sequence[str],
) -> list[RawRanking]:
    """处理 `_dense_raw_rankings` 相关逻辑。"""
    chunk_vectors = np.load(document_embeddings, mmap_mode="r")
    query_vectors = np.load(query_embeddings, mmap_mode="r")
    output: list[RawRanking] = []
    for case_index, record in enumerate(historical):
        query = np.asarray(query_vectors[case_index], dtype=np.float32)
        ids = tuple(record["rankings"]["qwen_dense"])
        scores: list[float] = []
        top_chunks: list[tuple[str, ...]] = []
        for document_id in ids:
            indexes = chunks_by_document[document_indexes[document_id]]
            values = np.asarray(chunk_vectors[indexes], dtype=np.float32) @ query
            ordered = sorted(
                range(len(indexes)),
                key=lambda local: (
                    -float(values[local]),
                    chunk_ids[int(indexes[local])],
                ),
            )
            scores.append(float(values[ordered[0]]))
            top_chunks.append(
                tuple(chunk_ids[int(indexes[local])] for local in ordered[:3])
            )
        output.append(RawRanking(ids, tuple(scores), tuple(top_chunks)))
    return output


def _route_map(ranking: RawRanking) -> dict[str, tuple[int, float, tuple[str, ...]]]:
    """处理 `_route_map` 相关逻辑。"""
    return {
        document_id: (rank, score, chunks)
        for rank, (document_id, score, chunks) in enumerate(
            zip(ranking.document_ids, ranking.scores, ranking.top_chunk_ids), 1
        )
    }


def _candidate_payload(
    dense: RawRanking,
    body: RawRanking,
    heading: RawRanking,
) -> list[dict[str, Any]]:
    """处理 `_candidate_payload` 相关逻辑。"""
    routes = {
        "dense": _route_map(dense),
        "bm25_body": _route_map(body),
        "bm25_heading": _route_map(heading),
    }
    candidates = set().union(*(values for values in routes.values()))
    payload: list[dict[str, Any]] = []
    for document_id in sorted(
        candidates,
        key=lambda value: (
            min(route[value][0] for route in routes.values() if value in route),
            value,
        ),
    ):
        item: dict[str, Any] = {"document_id": document_id}
        for route_name, values in routes.items():
            value = values.get(document_id)
            item[f"{route_name}_raw_score"] = None if value is None else value[1]
            item[f"{route_name}_rank"] = None if value is None else value[0]
            item[f"{route_name}_top_chunk_ids"] = (
                [] if value is None else list(value[2])
            )
        payload.append(item)
    return payload


def _fit_calibrators(
    rankings: dict[str, Sequence[RawRanking]], method: str
) -> dict[str, ScoreCalibrator]:
    """处理 `_fit_calibrators` 相关逻辑。"""
    values = {
        route: [score for ranking in items for score in ranking.scores]
        for route, items in rankings.items()
    }

    def percentile(route: str) -> ScoreCalibrator:
        """处理 `percentile` 相关逻辑。"""
        scores = values[route]
        return (
            PercentileScoreCalibrator.fit(scores)
            if len(scores) >= 2
            else IdentityScoreCalibrator()
        )

    def robust(route: str) -> ScoreCalibrator:
        """处理 `robust` 相关逻辑。"""
        scores = values[route]
        if len(scores) < 2 or min(scores) == max(scores):
            return IdentityScoreCalibrator()
        return RobustMinMaxScoreCalibrator.fit(scores)

    if method == "cosine+global_percentile":
        return {
            "dense": CosineScoreCalibrator(),
            "bm25_body": percentile("bm25_body"),
            "bm25_heading": percentile("bm25_heading"),
        }
    if method == "global_robust_minmax":
        return {route: robust(route) for route in values}
    raise ValueError(f"unknown calibration method: {method}")


def _calibrator_metadata(calibrator: ScoreCalibrator) -> dict[str, Any]:
    """处理 `_calibrator_metadata` 相关逻辑。"""
    if isinstance(calibrator, PercentileScoreCalibrator):
        values = calibrator.reference_scores
        return {
            "type": "global_percentile",
            "sample_count": len(values),
            "minimum": values[0],
            "maximum": values[-1],
        }
    return {"type": type(calibrator).__name__, **asdict(calibrator)}


def evaluate_dataset(arguments: argparse.Namespace, dataset: str) -> dict[str, Any]:
    """评估 `dataset` 相关数据。

    Args:
        arguments: argparse.Namespace => `arguments` 参数。
        dataset: str => `dataset` 参数。

    Returns:
        dict[str, Any] => 处理结果。
    """
    data = _load_dataset(dataset, arguments.data_root)
    cases: tuple[BenchmarkCase, ...] = _selected_cases(
        data.cases, arguments.max_queries
    )
    collection = build_benchmark_collection(data)
    chunks = collection.chunks
    chunk_ids = [chunk.chunk_id for chunk in chunks]
    document_ids = sorted({chunk.document_id for chunk in chunks})
    document_indexes = {value: index for index, value in enumerate(document_ids)}
    chunk_document_indexes = np.asarray(
        [document_indexes[chunk.document_id] for chunk in chunks], dtype=np.int64
    )
    grouped: list[list[int]] = [[] for _value in document_ids]
    for chunk_index, document_index in enumerate(chunk_document_indexes):
        grouped[int(document_index)].append(chunk_index)
    chunks_by_document = [np.asarray(value, dtype=np.int64) for value in grouped]

    input_dir = arguments.input_root / dataset
    historical = _read_jsonl(input_dir / "retrieval.jsonl")
    if len(historical) != len(cases):
        raise ValueError("historical retrieval rows do not match benchmark cases")
    dense = _dense_raw_rankings(
        historical,
        input_dir / "cache/document_embeddings.float16.npy",
        input_dir / "cache/query_embeddings.float16.npy",
        document_indexes,
        chunks_by_document,
        chunk_ids,
    )
    body_backend = _RawBm25(
        [chunk.bm25_body for chunk in chunks], chunk_document_indexes, chunk_ids
    )
    heading_backend = _RawBm25(
        [chunk.bm25_heading for chunk in chunks], chunk_document_indexes, chunk_ids
    )
    body: list[RawRanking] = []
    heading: list[RawRanking] = []
    for index, case in enumerate(cases, 1):
        body.append(body_backend.rank(case.query, document_ids, arguments.depth))
        heading.append(heading_backend.rank(case.query, document_ids, arguments.depth))
        if index % 250 == 0 or index == len(cases):
            print(f"{dataset}: raw_bm25={index}/{len(cases)}", flush=True)

    routes_by_query = [
        {
            "dense": dense[index].items(),
            "bm25_body": body[index].items(),
            "bm25_heading": heading[index].items(),
        }
        for index in range(len(cases))
    ]
    output_dir = arguments.output_root / dataset
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "fusion_raw.jsonl"
    with raw_path.open("w", encoding="utf-8") as handle:
        for index, case in enumerate(cases):
            handle.write(
                json.dumps(
                    {
                        "case_index": index,
                        "case_id": case.case_id,
                        "query": case.query,
                        "relevant_document_ids": sorted(case.relevant_document_ids),
                        "candidates": _candidate_payload(
                            dense[index], body[index], heading[index]
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
    print(f"{dataset}: raw_artifact={raw_path}", flush=True)
    raw_rankings = {"dense": dense, "bm25_body": body, "bm25_heading": heading}
    calibrator_sets = {
        method: _fit_calibrators(raw_rankings, method)
        for method in ("cosine+global_percentile", "global_robust_minmax")
    }

    dense_ids = [ranking.document_ids for ranking in dense]
    historical_rrf = [record["rankings"]["hybrid_rrf"] for record in historical]
    equal_rrf = [
        [item.chunk_id for item in reciprocal_rank_fusion(routes, rrf_k=60, limit=20)]
        for routes in routes_by_query
    ]
    metrics: dict[str, Any] = {
        "dense_only": _metrics(cases, dense_ids),
        "historical_equal_rrf": _metrics(cases, historical_rrf),
        "equal_rrf_three_route": _metrics(cases, equal_rrf),
    }
    experiments: list[dict[str, Any]] = []
    for alpha in (0.80, 0.85, 0.90, 0.95, 1.00):
        for beta in (0.60, 0.75, 1.00):
            weights = {
                "dense": alpha,
                "bm25_body": (1.0 - alpha) * beta,
                "bm25_heading": (1.0 - alpha) * (1.0 - beta),
            }
            weighted = [
                [
                    item.chunk_id
                    for item in weighted_reciprocal_rank_fusion(
                        routes, weights, rrf_k=60, limit=20
                    )
                ]
                for routes in routes_by_query
            ]
            experiments.append(
                {
                    "method": "weighted_rrf",
                    "alpha": alpha,
                    "beta": beta,
                    "calibration": "rank_only",
                    "lexical_gate": False,
                    "metrics": _metrics(cases, weighted),
                }
            )
            for calibration_name, calibrators in calibrator_sets.items():
                for gate_enabled in (False, True):
                    fused = [
                        [
                            item.chunk_id
                            for item in score_level_weighted_fusion(
                                routes,
                                calibrators,
                                query=case.query,
                                alpha=alpha,
                                beta=beta,
                                limit=20,
                                lexical_gate=None if gate_enabled else 1.0,
                            ).ranking
                        ]
                        for case, routes in zip(cases, routes_by_query)
                    ]
                    experiments.append(
                        {
                            "method": "score_weighted",
                            "alpha": alpha,
                            "beta": beta,
                            "calibration": calibration_name,
                            "lexical_gate": gate_enabled,
                            "metrics": _metrics(cases, fused),
                        }
                    )

    best = max(
        (item for item in experiments if item["method"] == "score_weighted"),
        key=lambda item: float(item["metrics"]["ndcg@10"]),
    )
    summary = {
        "schema_version": "esa-score-fusion-ablation-1.0",
        "dataset": dataset,
        "query_count": len(cases),
        "candidate_depth_per_route": arguments.depth,
        "raw_score_artifact": str(raw_path),
        "calibration_fit": (
            "unsupervised global candidate-score distributions; no qrels used"
        ),
        "calibrators": {
            name: {
                route: _calibrator_metadata(calibrator)
                for route, calibrator in values.items()
            }
            for name, values in calibrator_sets.items()
        },
        "baselines": metrics,
        "experiments": experiments,
        "best_score_weighted_by_ndcg@10": best,
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"dataset": dataset, "best": best}, ensure_ascii=False))
    return summary


def _parser() -> argparse.ArgumentParser:
    """处理 `_parser` 相关逻辑。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=(*DATASETS, "all"), default="all")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--depth", type=int, default=100)
    parser.add_argument("--max-queries", type=int, default=0)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="combine existing per-dataset summaries without recomputing retrieval",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """运行当前模块的命令行入口。

    Args:
        argv: list[str] | None => `argv` 参数。

    Returns:
        int => 处理结果。
    """
    arguments = _parser().parse_args(argv)
    datasets = DATASETS if arguments.dataset == "all" else (arguments.dataset,)
    summaries = (
        {
            dataset: json.loads(
                (arguments.output_root / dataset / "summary.json").read_text()
            )
            for dataset in datasets
        }
        if arguments.report_only
        else {dataset: evaluate_dataset(arguments, dataset) for dataset in datasets}
    )
    report = {
        "schema_version": "esa-score-fusion-report-1.0",
        "datasets": {
            name: {
                "baselines": value["baselines"],
                "best_score_weighted_by_ndcg@10": value[
                    "best_score_weighted_by_ndcg@10"
                ],
            }
            for name, value in summaries.items()
        },
    }
    arguments.output_root.mkdir(parents=True, exist_ok=True)
    (arguments.output_root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
