"""Final bounded Qwen reranker experiment: instruction, top-3 and prior fusion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..retrieval.calibration import CosineScoreCalibrator, PercentileScoreCalibrator
from ..retrieval.contracts import RankedItem
from ..retrieval.fusion import score_level_weighted_fusion
from ..retrieval.reranking import aggregate_chunk_scores
from .external_benchmarks import build_benchmark_collection
from .qwen_ablation import (
    QUERY_INSTRUCTION,
    RERANKER_MODEL,
    TASK_RERANK_INSTRUCTIONS,
    _QwenReranker,
    _load_dataset,
    _metrics,
    _read_jsonl,
    _revision,
)

DATASETS = ("scifact", "xor-tydi", "m3docvqa")
DEFAULT_DATA_ROOT = Path("/home/karatani/esa/artifacts/rag/benchmarks/datasets")
DEFAULT_FUSION_ROOT = Path(
    "/home/karatani/esa/artifacts/rag/benchmarks/weighted-fusion-20260811"
)
DEFAULT_OUTPUT_ROOT = Path(
    "/home/karatani/esa/artifacts/rag/benchmarks/reranker-final-20260811"
)


def _route_items(row: dict[str, Any], route: str) -> list[RankedItem]:
    values = [
        candidate
        for candidate in row["candidates"]
        if candidate[f"{route}_rank"] is not None
    ]
    values.sort(key=lambda item: (item[f"{route}_rank"], item["document_id"]))
    return [
        RankedItem(item["document_id"], float(item[f"{route}_raw_score"]))
        for item in values
    ]


def _calibrators(rows: list[dict[str, Any]]):
    body = [
        float(candidate["bm25_body_raw_score"])
        for row in rows
        for candidate in row["candidates"]
        if candidate["bm25_body_raw_score"] is not None
    ]
    heading = [
        float(candidate["bm25_heading_raw_score"])
        for row in rows
        for candidate in row["candidates"]
        if candidate["bm25_heading_raw_score"] is not None
    ]
    # Empty routes remain explicit zero-contribution routes.
    fallback = PercentileScoreCalibrator.fit([0.0, 1.0])
    return {
        "dense": CosineScoreCalibrator(),
        "bm25_body": PercentileScoreCalibrator.fit(body) if body else fallback,
        "bm25_heading": PercentileScoreCalibrator.fit(heading) if heading else fallback,
    }


def _prior(
    row: dict[str, Any],
    calibrators,
    config: dict[str, Any],
    source: str,
) -> list[RankedItem]:
    routes = {
        route: _route_items(row, route)
        for route in ("dense", "bm25_body", "bm25_heading")
    }
    if source == "dense":
        return [
            RankedItem(item.chunk_id, calibrators["dense"].calibrate(item.score))
            for item in routes["dense"][:20]
        ]
    return list(
        score_level_weighted_fusion(
            routes,
            calibrators,
            query=row["query"],
            alpha=float(config["alpha"]),
            beta=float(config["beta"]),
            limit=20,
            lexical_gate=None if config["lexical_gate"] else 1.0,
        ).ranking
    )


def _top_chunks(candidate: dict[str, Any]) -> list[str]:
    output: list[str] = []
    for route in ("dense", "bm25_body", "bm25_heading"):
        for chunk_id in candidate[f"{route}_top_chunk_ids"]:
            if chunk_id not in output:
                output.append(chunk_id)
            if len(output) == 3:
                return output
    return output


def _score_query(
    model: _QwenReranker,
    query: str,
    documents: list[str],
    instruction: str,
    batch_size: int,
) -> list[float]:
    scores: list[float] = []
    for start in range(0, len(documents), batch_size):
        scores.extend(
            model.score(query, documents[start : start + batch_size], instruction)
        )
    return scores


def _blend(
    prior: list[RankedItem], reranker: dict[str, float], prior_weight: float
) -> list[str]:
    if prior_weight == 1.0:
        return [item.chunk_id for item in prior]
    indexed = list(enumerate(prior))
    indexed.sort(
        key=lambda value: (
            -(
                prior_weight * value[1].score
                + (1.0 - prior_weight) * reranker[value[1].chunk_id]
            ),
            value[0],
            value[1].chunk_id,
        )
    )
    return [item.chunk_id for _rank, item in indexed]


def run_dataset(arguments: argparse.Namespace, dataset: str) -> dict[str, Any]:
    fusion_dir = arguments.fusion_root / dataset
    rows = _read_jsonl(fusion_dir / "fusion_raw.jsonl")
    fusion_summary = json.loads((fusion_dir / "summary.json").read_text())
    best = fusion_summary["best_score_weighted_by_ndcg@10"]
    calibrators = _calibrators(rows)
    data = _load_dataset(dataset, arguments.data_root)
    cases = data.cases
    if len(cases) != len(rows):
        raise ValueError("fusion rows do not match benchmark cases")
    collection = build_benchmark_collection(data)
    chunks = {chunk.chunk_id: chunk for chunk in collection.chunks}
    model = _QwenReranker(RERANKER_MODEL, arguments.max_length)
    output_dir = arguments.output_root / dataset
    output_dir.mkdir(parents=True, exist_ok=True)
    signal_path = output_dir / "signals.jsonl"
    signals: list[dict[str, Any]] = []
    with signal_path.open("w", encoding="utf-8") as handle:
        for index, row in enumerate(rows):
            candidate_by_id = {
                candidate["document_id"]: candidate for candidate in row["candidates"]
            }
            priors = {
                source: _prior(row, calibrators, best, source)
                for source in ("best_score_fusion", "dense")
            }
            document_ids = list(
                dict.fromkeys(
                    item.chunk_id for values in priors.values() for item in values
                )
            )
            chunk_ids_by_document = {
                document_id: _top_chunks(candidate_by_id[document_id])
                for document_id in document_ids
            }
            flat = [
                chunk_id
                for document_id in document_ids
                for chunk_id in chunk_ids_by_document[document_id]
            ]
            documents = [chunks[chunk_id].dense_text for chunk_id in flat]
            instruction_scores = {}
            for name, instruction in (
                ("default", QUERY_INSTRUCTION),
                ("task_specific", TASK_RERANK_INSTRUCTIONS[dataset]),
            ):
                values = _score_query(
                    model,
                    row["query"],
                    documents,
                    instruction,
                    arguments.batch_size,
                )
                cursor = 0
                by_document = {}
                for document_id in document_ids:
                    count = len(chunk_ids_by_document[document_id])
                    by_document[document_id] = values[cursor : cursor + count]
                    cursor += count
                instruction_scores[name] = by_document
            value = {
                "case_index": index,
                "case_id": row["case_id"],
                "priors": {
                    name: [
                        {"document_id": item.chunk_id, "score": item.score}
                        for item in prior
                    ]
                    for name, prior in priors.items()
                },
                "top_chunk_ids": chunk_ids_by_document,
                "reranker_scores": instruction_scores,
            }
            handle.write(json.dumps(value, sort_keys=True) + "\n")
            handle.flush()
            signals.append(value)
            if (index + 1) % 25 == 0 or index + 1 == len(rows):
                print(f"{dataset}: reranked={index + 1}/{len(rows)}", flush=True)

    experiments = []
    for prior_source in ("best_score_fusion", "dense"):
        for instruction in ("default", "task_specific"):
            for aggregation in ("single", "max", "mean"):
                for prior_weight in (0.80, 0.90, 0.95, 1.00):
                    rankings = []
                    for signal in signals:
                        prior = [
                            RankedItem(item["document_id"], float(item["score"]))
                            for item in signal["priors"][prior_source]
                        ]
                        rerank = {}
                        for item in prior:
                            scores = signal["reranker_scores"][instruction][
                                item.chunk_id
                            ]
                            rerank[item.chunk_id] = (
                                scores[0]
                                if aggregation == "single"
                                else aggregate_chunk_scores(scores, aggregation)
                            )
                        rankings.append(_blend(prior, rerank, prior_weight))
                    experiments.append(
                        {
                            "prior": prior_source,
                            "instruction": instruction,
                            "chunk_aggregation": aggregation,
                            "prior_weight": prior_weight,
                            "metrics": _metrics(cases, rankings),
                        }
                    )
    baseline = next(
        item
        for item in experiments
        if item["prior"] == "best_score_fusion" and item["prior_weight"] == 1.0
    )
    beneficial = [
        item
        for item in experiments
        if item["prior_weight"] < 1.0
        and item["metrics"]["ndcg@10"] > baseline["metrics"]["ndcg@10"]
    ]
    summary = {
        "schema_version": "esa-reranker-final-ablation-1.0",
        "dataset": dataset,
        "query_count": len(cases),
        "model": str(RERANKER_MODEL),
        "revision": _revision(RERANKER_MODEL),
        "variables": {
            "instructions": ["default", "task_specific"],
            "chunk_aggregation": ["single", "max", "mean"],
            "prior_weight": [0.80, 0.90, 0.95, 1.00],
        },
        "standalone_reranker_tested": False,
        "signals": str(signal_path),
        "experiments": experiments,
        "best_beneficial": (
            max(beneficial, key=lambda item: item["metrics"]["ndcg@10"])
            if beneficial
            else None
        ),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=(*DATASETS, "all"), default="all")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--fusion-root", type=Path, default=DEFAULT_FUSION_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--max-length", type=int, default=1024)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    datasets = DATASETS if arguments.dataset == "all" else (arguments.dataset,)
    reports = {dataset: run_dataset(arguments, dataset) for dataset in datasets}
    arguments.output_root.mkdir(parents=True, exist_ok=True)
    (arguments.output_root / "report.json").write_text(
        json.dumps(
            {"schema_version": "esa-reranker-final-report-1.0", "datasets": reports},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
