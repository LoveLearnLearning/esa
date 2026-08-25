"""Answer-centric retrieval metric regression tests."""

from __future__ import annotations

import json

import pytest

from backend.agent.rag.evaluation.answer_quality import (
    AnswerFacet,
    AnswerQualityCase,
    EvidenceJudgment,
    UnjudgedRankingError,
    evaluate_answer_quality,
    evaluate_frozen_pool,
    load_answer_quality_cases,
)


def _case() -> AnswerQualityCase:
    return AnswerQualityCase(
        case_id="case",
        query="为什么使用缓存？",
        reference_answer="缓存利用局部性缩短平均访问时间。",
        facets=(
            AnswerFacet("locality", "说明缓存利用时间或空间局部性"),
            AnswerFacet("latency", "说明缓存降低平均访问时间"),
        ),
        source_gold_document_ids=frozenset({"preferred-source"}),
        judgments=(
            EvidenceJudgment(
                "alternate-complete",
                3,
                frozenset({"locality", "latency"}),
                "另一教材中的完整正确答案。",
            ),
            EvidenceJudgment(
                "preferred-partial",
                2,
                frozenset({"locality"}),
                "指定教材，但当前 Chunk 只覆盖局部性。",
            ),
            EvidenceJudgment(
                "topical",
                1,
                frozenset(),
                "只提到缓存，没有回答机制或效果。",
            ),
        ),
    )


def test_answer_quality_rewards_complete_alternate_source() -> None:
    metrics = evaluate_answer_quality(
        [_case()],
        {"case": ["alternate-complete", "preferred-partial", "topical"]},
        {
            "alternate-complete": "alternate-source",
            "preferred-partial": "preferred-source",
            "topical": "alternate-source",
        },
    )

    assert metrics.direct_answer_hit_at_1 == 1.0
    assert metrics.answer_bearing_hit_at_1 == 1.0
    assert metrics.complete_answer_rate_at_5 == 1.0
    assert metrics.source_hit_at_1 == 0.0
    assert metrics.source_hit_at_3 == 1.0


def test_top_five_can_combine_partial_evidence_to_cover_all_facets() -> None:
    case = _case()
    second = EvidenceJudgment(
        "latency-partial",
        2,
        frozenset({"latency"}),
        "补充平均访问时间效果。",
    )
    case = AnswerQualityCase(
        case.case_id,
        case.query,
        case.reference_answer,
        case.facets,
        case.source_gold_document_ids,
        (case.judgments[1], second, case.judgments[2]),
    )
    metrics = evaluate_answer_quality(
        [case],
        {"case": ["preferred-partial", "latency-partial", "topical"]},
        {
            "preferred-partial": "preferred-source",
            "latency-partial": "alternate-source",
            "topical": "alternate-source",
        },
    )

    assert metrics.direct_answer_hit_at_5 == 0.0
    assert metrics.facet_coverage_at_5 == 1.0
    assert metrics.complete_answer_rate_at_5 == 1.0


def test_topical_only_chunks_receive_no_answer_ndcg_gain() -> None:
    case = _case()
    metrics = evaluate_answer_quality(
        [case],
        {"case": ["topical"]},
        {"topical": "alternate-source"},
    )

    assert metrics.graded_ndcg_at_5 == 0.0


def test_unjudged_top_five_fails_closed() -> None:
    with pytest.raises(UnjudgedRankingError, match="unjudged Top-5"):
        evaluate_answer_quality(
            [_case()],
            {"case": ["new-candidate"]},
            {"new-candidate": "new-source"},
        )


def test_loader_validates_schema_and_collection_ids(tmp_path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "esa-answer-quality-benchmark-1.0",
                "collection_id": "collection",
                "annotation": {
                    "status": "audited",
                    "reviewer": "test-reviewer",
                    "reviewed_at": "2026-08-24",
                    "rubric_version": "test-1.0",
                    "audited_case_count": 1,
                    "audited_judgment_count": 1,
                },
                "cases": [
                    {
                        "case_id": "case",
                        "query": "query",
                        "reference_answer": "answer",
                        "facets": [
                            {"facet_id": "fact", "description": "required fact"}
                        ],
                        "source_gold_document_ids": ["document"],
                        "judgments": [
                            {
                                "chunk_id": "chunk",
                                "relevance": 3,
                                "covered_facet_ids": ["fact"],
                                "rationale": "complete answer",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    cases = load_answer_quality_cases(
        path,
        known_chunk_ids={"chunk"},
        known_document_ids={"document"},
        expected_collection_id="collection",
    )

    assert cases[0].judgments[0].relevance == 3


def test_loader_rejects_provisional_labels_by_default(tmp_path) -> None:
    path = tmp_path / "provisional.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "esa-answer-quality-benchmark-1.0",
                "collection_id": "collection",
                "annotation": {"status": "model_seed_requires_audit"},
                "cases": [
                    {
                        "case_id": "case",
                        "query": "query",
                        "reference_answer": "answer",
                        "facets": [
                            {"facet_id": "fact", "description": "required fact"}
                        ],
                        "source_gold_document_ids": ["document"],
                        "judgments": [
                            {
                                "chunk_id": "chunk",
                                "relevance": 3,
                                "covered_facet_ids": ["fact"],
                                "rationale": "model-proposed complete answer",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="require annotation.status='audited'"):
        load_answer_quality_cases(path)
    cases = load_answer_quality_cases(path, require_audited=False)
    assert cases[0].case_id == "case"


def test_frozen_pool_report_keeps_provisional_status(tmp_path) -> None:
    benchmark_path = tmp_path / "benchmark.json"
    pool_path = tmp_path / "pool.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "schema_version": "esa-answer-quality-benchmark-1.0",
                "collection_id": "collection",
                "annotation": {"status": "model_seed_requires_audit"},
                "cases": [
                    {
                        "case_id": "case",
                        "query": "query",
                        "reference_answer": "answer",
                        "facets": [
                            {"facet_id": "fact", "description": "required fact"}
                        ],
                        "source_gold_document_ids": ["preferred-document"],
                        "judgments": [
                            {
                                "chunk_id": "chunk",
                                "relevance": 3,
                                "covered_facet_ids": ["fact"],
                                "rationale": "complete answer",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    pool_path.write_text(
        json.dumps(
            {
                "schema_version": "esa-dense-ablation-pool-1.0",
                "collection_id": "collection",
                "profiles": {"dense": {"fusion_method": "dense"}},
                "chunks": {"chunk": {"document_id": "alternate-document"}},
                "cases": [
                    {"case_id": "case", "rankings": {"dense": ["chunk"]}}
                ],
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_frozen_pool(
        benchmark_path,
        pool_path,
        require_audited=False,
    )

    assert report["status"] == "provisional_not_for_decisions"
    assert report["profiles"]["dense"]["metrics"]["answer_bearing_hit_at_1"] == 1
    assert report["profiles"]["dense"]["metrics"]["source_hit_at_1"] == 0
    assert len(report["benchmark_sha256"]) == 64
