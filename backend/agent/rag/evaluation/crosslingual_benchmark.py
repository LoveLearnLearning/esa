# backend/agent/rag/evaluation/crosslingual_benchmark.py

"""人工 gold 的中文查询→英文语料评测 schema 与离线评测入口。

本模块只接受显式提供的 gold document IDs，不生成或猜测标签。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .external_benchmarks import BenchmarkCase
from .qwen_ablation import _metrics, _read_jsonl

PIPELINES = (
    "dense_original_zh",
    "bm25_original_zh",
    "bm25_translated_en",
    "dense_plus_translated_bm25",
    "dense_plus_expansion_translated_bm25",
)


@dataclass(frozen=True)
class ChineseEnglishCase:
    """封装 `ChineseEnglishCase` 的状态与行为。"""
    case_id: str
    query_zh: str
    gold_document_ids: frozenset[str]
    translation_en: str | None = None
    tags: tuple[str, ...] = ()

    def benchmark_case(self) -> BenchmarkCase:
        """处理 `benchmark_case` 相关逻辑。"""
        return BenchmarkCase(
            self.case_id, self.query_zh, self.gold_document_ids, self.tags
        )


def load_cases(path: Path) -> tuple[ChineseEnglishCase, ...]:
    """加载 `cases` 相关数据。

    Args:
        path: Path => 目标路径。

    Returns:
        tuple[ChineseEnglishCase, ...] => 处理结果。
    """
    cases: list[ChineseEnglishCase] = []
    seen: set[str] = set()
    for value in _read_jsonl(path):
        case_id = str(value.get("case_id", "")).strip()
        query = str(value.get("query_zh", "")).strip()
        gold = frozenset(str(item) for item in value.get("gold_document_ids", ()))
        if not case_id or case_id in seen:
            raise ValueError("case_id must be non-empty and unique")
        if not query or not gold:
            raise ValueError("query_zh and human gold_document_ids are required")
        seen.add(case_id)
        translation = value.get("translation_en")
        cases.append(
            ChineseEnglishCase(
                case_id,
                query,
                gold,
                str(translation).strip() if translation else None,
                tuple(str(item) for item in value.get("tags", ())),
            )
        )
    if not cases:
        raise ValueError("benchmark must contain at least one human-gold case")
    return tuple(cases)


def evaluate_replay(case_path: Path, result_path: Path) -> dict[str, Any]:
    """评测已保存的五路排名；Embedding、BM25 或翻译器均可在外部替换。"""

    cases = load_cases(case_path)
    rows = _read_jsonl(result_path)
    by_id = {str(row.get("case_id")): row for row in rows}
    if set(by_id) != {case.case_id for case in cases}:
        raise ValueError("result case IDs must exactly match benchmark case IDs")
    metrics = {}
    benchmark_cases = [case.benchmark_case() for case in cases]
    for pipeline in PIPELINES:
        rankings = []
        for case in cases:
            value = by_id[case.case_id].get("rankings", {}).get(pipeline)
            if not isinstance(value, list):
                raise ValueError(f"missing ranking for pipeline {pipeline}")
            rankings.append([str(item) for item in value])
        metrics[pipeline] = _metrics(benchmark_cases, rankings)
    return {
        "schema_version": "esa-zh-en-retrieval-benchmark-1.0",
        "gold_policy": "explicit human-provided document IDs only",
        "query_count": len(cases),
        "metrics": metrics,
    }


def _parser() -> argparse.ArgumentParser:
    """处理 `_parser` 相关逻辑。"""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--cases", type=Path, required=True)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--cases", type=Path, required=True)
    evaluate.add_argument("--results", type=Path, required=True)
    evaluate.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """运行当前模块的命令行入口。"""
    arguments = _parser().parse_args(argv)
    if arguments.command == "validate":
        print(json.dumps({"query_count": len(load_cases(arguments.cases))}))
        return 0
    report = evaluate_replay(arguments.cases, arguments.results)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if arguments.output:
        arguments.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
