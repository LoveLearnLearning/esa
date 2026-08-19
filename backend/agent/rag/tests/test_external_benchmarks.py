# backend/agent/rag/tests/test_external_benchmarks.py

"""验证 `external_benchmarks` 相关行为与回归场景。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.agent.rag.evaluation.external_benchmarks import (
    BenchmarkCase,
    BenchmarkData,
    CorpusPart,
    evaluate_benchmark,
    load_m3docvqa,
    load_scifact,
    load_xor_tydi_gold,
)


def test_load_scifact_uses_positive_test_qrels(tmp_path: Path) -> None:
    """验证 `load_scifact_uses_positive_test_qrels` 场景。"""
    (tmp_path / "qrels").mkdir()
    (tmp_path / "corpus.jsonl").write_text(
        json.dumps({"_id": "doc", "title": "Alpha", "text": "alpha body"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "queries.jsonl").write_text(
        json.dumps({"_id": "query", "text": "alpha"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "qrels/test.tsv").write_text(
        "query-id\tcorpus-id\tscore\nquery\tdoc\t1\n",
        encoding="utf-8",
    )

    data = load_scifact(tmp_path)

    assert len(data.parts) == 1
    assert data.cases[0].relevant_document_ids == {"doc"}


def test_load_xor_gold_deduplicates_paragraphs(tmp_path: Path) -> None:
    """验证 `load_xor_gold_deduplicates_paragraphs` 场景。"""
    target = tmp_path / "xorqa_reading_comprehension_format"
    target.mkdir()
    payload = {
        "version": "1",
        "data": [
            {
                "title": "title",
                "paragraphs": [
                    {
                        "context": "shared context",
                        "qas": [
                            {"id": "one", "question": "q1", "lang": "ja"},
                            {"id": "two", "question": "q2", "lang": "ko"},
                        ],
                    }
                ],
            }
        ],
    }
    (target / "gp_squad_dev_data.json").write_text(json.dumps(payload), encoding="utf-8")

    data = load_xor_tydi_gold(tmp_path)

    assert len(data.parts) == 1
    assert len(data.cases) == 2
    assert data.cases[0].relevant_document_ids == data.cases[1].relevant_document_ids


def test_evaluate_benchmark_calls_rag_and_writes_layered_metrics(tmp_path: Path) -> None:
    """验证 `evaluate_benchmark_calls_rag_and_writes_layered_metrics` 场景。"""
    data = BenchmarkData(
        name="fixture",
        scope="unit test",
        parts=(
            CorpusPart("relevant", "Neptune", "Neptune is an ice giant planet."),
            CorpusPart("other", "Cooking", "Bread is baked in an oven."),
        ),
        cases=(
            BenchmarkCase("q1", "Neptune ice giant", frozenset({"relevant"})),
        ),
        source={"fixture": "true"},
    )

    output, summary = evaluate_benchmark(data, tmp_path)

    assert summary["metrics"]["final"]["hit_rate@1"] == 1.0
    assert summary["metrics"]["bm25_body"]["hit_rate@1"] == 1.0
    assert (output / "summary.json").is_file()
    assert (output / "results.jsonl").is_file()


def test_load_m3docvqa_uses_cached_pages_and_document_gold(tmp_path: Path) -> None:
    """验证 `load_m3docvqa_uses_cached_pages_and_document_gold` 场景。"""
    (tmp_path / "multimodalqa").mkdir()
    (tmp_path / "dev_doc_ids.json").write_text('["doc"]', encoding="utf-8")
    cache = tmp_path / "extracted_pages.jsonl"
    cache.write_text(
        json.dumps({"document_id": "doc", "page_index": 2, "text": "page text"})
        + "\n",
        encoding="utf-8",
    )
    example = {
        "qid": "question",
        "question": "What is on the page?",
        "metadata": {"type": "TextQ", "modalities": ["text"]},
        "supporting_context": [{"doc_id": "doc", "doc_part": "text"}],
    }
    (tmp_path / "multimodalqa/MMQA_dev.jsonl").write_text(
        json.dumps(example) + "\n",
        encoding="utf-8",
    )

    data = load_m3docvqa(tmp_path, cache)

    assert data.parts[0].page_index == 2
    assert data.cases[0].relevant_document_ids == {"doc"}
    assert data.cases[0].tags == ("type:TextQ", "modality:text", "dev")
