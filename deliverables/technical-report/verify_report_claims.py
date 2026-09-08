#!/usr/bin/env python3
"""Verify the repository-backed claims used by the competition report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


REPORT_DIR = Path(__file__).resolve().parent
REPO = REPORT_DIR.parents[1]
DATASET = REPO / "backend/scripts/dataset"
KNOWLEDGE_V1 = REPO / "data/knowledge_base/v1"
EVIDENCE = REPORT_DIR / "evidence"

MAIN_FINGERPRINT = "d441611fb5556b53#440"
CASE_IDS = (
    "calc_000_0",
    "s002_修改参数_0020",
    "record_learning_evidence_正例_practice_0012",
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")
    print(f"OK  {label}: {actual}")


def verify_knowledge_assets() -> None:
    expected_counts = {
        "courses.jsonl": 16,
        "knowledge_points.jsonl": 215,
        "prerequisites.jsonl": 186,
        "source_registry.jsonl": 16,
        "gold_answer.jsonl": 48,
        "gold_retrieval.jsonl": 430,
        "question_bank.jsonl": 645,
        "concept_cards.jsonl": 215,
    }
    for filename, expected in expected_counts.items():
        assert_equal(len(load_jsonl(KNOWLEDGE_V1 / filename)), expected, filename)

    sources = load_jsonl(KNOWLEDGE_V1 / "source_registry.jsonl")
    assert_equal(
        sum(item.get("availability") == "bundled" for item in sources),
        12,
        "bundled knowledge sources",
    )
    assert_equal(
        sum(item.get("availability") == "dynamic_url" for item in sources),
        3,
        "dynamic knowledge sources",
    )
    assert_equal(
        sum(item.get("availability") == "reference_only_url" for item in sources),
        1,
        "reference-only knowledge sources",
    )


def verify_runtime_graph() -> None:
    courses = points = prerequisites = 0
    graph_dir = REPO / "backend/agent/memories/data/knowledge_graph"
    for filename in ("core_courses.yaml", "elective_courses.yaml"):
        data = yaml.safe_load((graph_dir / filename).read_text(encoding="utf-8"))
        for course in data["courses"]:
            courses += 1
            points += len(course.get("points", []))
            prerequisites += len(course.get("prerequisites", []))
    assert_equal(courses, 47, "runtime graph courses")
    assert_equal(points, 479, "runtime graph knowledge points")
    assert_equal(prerequisites, 448, "runtime graph prerequisite edges")


def verify_dataset_counts() -> None:
    ir_total = sum(
        len(load_jsonl(path)) for path in (DATASET / "data/ir").glob("*.jsonl")
    )
    assert_equal(ir_total, 1421, "IR samples")

    stats = load_json(DATASET / "data/eval/eval_stats.json")
    for key, expected in {
        "train_total": 1094,
        "train_held_for_review": 1,
        "eval_total": 277,
        "eval_questions": 440,
        "supp_total": 49,
        "supp_questions": 55,
    }.items():
        assert_equal(stats[key], expected, f"eval_stats.{key}")

    sys.path.insert(0, str(DATASET))
    from esa.ir import load_samples
    from esa.split import group_split

    split = group_split(load_samples(DATASET / "data/eval/train_ir.jsonl"))
    assert_equal(len(split["train"]), 1003, "render split train")
    assert_equal(len(split["validation"]), 43, "render split validation")
    assert_equal(len(split["test"]), 48, "render split test")

    adjudication = load_json(DATASET / "data/eval/refusal_adjudication.json")
    assert_equal(len(adjudication["verdicts"]), 264, "refusal verdicts")


def verify_cases() -> None:
    predictions = load_jsonl(EVIDENCE / "pred_nothink_ep10_95348.jsonl")
    assert_equal(predictions[0]["_meta"]["eval_fingerprint"], MAIN_FINGERPRINT, "eval fingerprint")
    predicted_ids = {item["id"] for item in predictions if "id" in item}
    report = load_json(EVIDENCE / "report_nothink_ep10_95348.json")
    metrics = report["_items"]

    call_metrics = (
        "格式合法率",
        "工具选择准确率",
        "工具调用完全正确率",
        "参数完全匹配率",
        "参数schema合法率",
    )
    response_metrics = ("格式合法率", "结果响应率", "结果忠实度")

    for case_id in CASE_IDS:
        if case_id not in predicted_ids or f"{case_id}#respond" not in predicted_ids:
            raise AssertionError(f"missing prediction rows for {case_id}")
        for metric in call_metrics:
            score = metrics.get(metric, {}).get(case_id)
            if score is not None:
                assert_equal(score, 1, f"{case_id} / {metric}")
        for metric in response_metrics:
            assert_equal(
                metrics[metric][f"{case_id}#respond"],
                1,
                f"{case_id}#respond / {metric}",
            )


def main() -> None:
    verify_knowledge_assets()
    verify_runtime_graph()
    verify_dataset_counts()
    verify_cases()
    print("All report claims verified.")


if __name__ == "__main__":
    main()
