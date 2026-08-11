from __future__ import annotations

import json

import pytest

from backend.agent.rag.evaluation.crosslingual_benchmark import (
    PIPELINES,
    evaluate_replay,
    load_cases,
)


def test_crosslingual_schema_requires_explicit_gold(tmp_path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text('{"case_id":"1","query_zh":"什么是 TCP？"}\n')
    with pytest.raises(ValueError, match="gold_document_ids"):
        load_cases(path)


def test_crosslingual_replay_evaluates_all_required_pipelines(tmp_path) -> None:
    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        json.dumps(
            {
                "case_id": "1",
                "query_zh": "什么是 TCP？",
                "translation_en": "What is TCP?",
                "gold_document_ids": ["gold"],
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    results = tmp_path / "results.jsonl"
    results.write_text(
        json.dumps(
            {
                "case_id": "1",
                "rankings": {name: ["gold", "other"] for name in PIPELINES},
            }
        )
        + "\n"
    )
    report = evaluate_replay(cases, results)
    assert set(report["metrics"]) == set(PIPELINES)
    assert all(value["hit@1"] == 1.0 for value in report["metrics"].values())
