"""Deterministic metrics for the live personal federation evaluator."""

from __future__ import annotations

import pytest

from backend.agent.rag.evaluation.personal_federation import (
    fuse_sources,
    retrieval_metrics,
)


CASES = [
    {"case_id": "one", "expected_source_refs": ["a"]},
    {"case_id": "two", "expected_source_refs": ["b", "c"]},
]


def test_fusion_deduplicates_sources_and_retains_scope_provenance():
    fused = fuse_sources(["a", "b"], ["b", "c"], limit=3)

    assert [item.source_ref for item in fused] == ["b", "a", "c"]
    assert fused[0].scope == "global+personal"
    assert [item.rank for item in fused] == [1, 2, 3]


def test_metrics_report_hit_mrr_and_ndcg_over_exact_cases():
    metrics = retrieval_metrics(
        CASES,
        {"one": ["x", "a"], "two": ["b", "x", "c"]},
        limit=3,
    )

    assert metrics["case_count"] == 2
    assert metrics["hit@3"] == 1.0
    assert metrics["mrr"] == 0.75
    assert 0 < metrics["ndcg@3"] <= 1


def test_metrics_refuse_empty_eligible_case_set():
    with pytest.raises(ValueError, match="at least one"):
        retrieval_metrics([], {}, limit=5)
