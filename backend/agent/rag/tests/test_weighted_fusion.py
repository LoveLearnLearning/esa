"""Dense 主导融合、词法 gate、Reranker prior 与查询职责拆分测试。"""

from __future__ import annotations

import math

import pytest

from backend.agent.rag.chunk import ContentRole
from backend.agent.rag.retrieval.calibration import (
    CosineScoreCalibrator,
    IdentityScoreCalibrator,
    IsotonicScoreCalibrator,
    LogisticScoreCalibrator,
    PercentileScoreCalibrator,
    RobustMinMaxScoreCalibrator,
)
from backend.agent.rag.retrieval.contracts import RankedItem, RetrievalConfig
from backend.agent.rag.retrieval.fusion import (
    lexical_confidence,
    score_level_weighted_fusion,
)
from backend.agent.rag.retrieval.query import (
    GlossaryQueryExpansion,
    RuleBasedQueryIntent,
    RuleBasedQueryProcessor,
)
from backend.agent.rag.retrieval.reranking import (
    aggregate_chunk_scores,
    blend_retrieval_and_reranker,
)


def _routes() -> dict[str, list[RankedItem]]:
    return {
        "dense": [RankedItem("dense-a", 0.9), RankedItem("shared", 0.8)],
        "bm25_body": [RankedItem("body-only", 12.0), RankedItem("shared", 8.0)],
        "bm25_heading": [RankedItem("heading-only", 9.0)],
    }


def _calibrators():
    return {
        "dense": CosineScoreCalibrator(),
        "bm25_body": RobustMinMaxScoreCalibrator(0.0, 20.0),
        "bm25_heading": RobustMinMaxScoreCalibrator(0.0, 20.0),
    }


def test_score_fusion_preserves_raw_scores_ranks_and_missing_routes() -> None:
    result = score_level_weighted_fusion(
        _routes(), _calibrators(), query="RFC 793", alpha=0.9, beta=0.75
    )
    by_id = {item.chunk_id: item for item in result.candidates}
    assert by_id["body-only"].dense_raw_score is None
    assert by_id["body-only"].bm25_body_raw_score == 12.0
    assert by_id["body-only"].bm25_body_rank == 1
    assert by_id["heading-only"].bm25_heading_rank == 1
    assert all(math.isfinite(item.final_score) for item in result.candidates)


def test_dense_only_is_exactly_alpha_one_and_reproducible() -> None:
    first = score_level_weighted_fusion(
        _routes(), _calibrators(), query="ordinary question", alpha=1.0, beta=0.6
    )
    second = score_level_weighted_fusion(
        dict(reversed(list(_routes().items()))),
        _calibrators(),
        query="ordinary question",
        alpha=1.0,
        beta=1.0,
    )
    assert first.ranking == second.ranking == tuple(_routes()["dense"])


def test_global_percentile_does_not_promote_weak_query_top_to_one() -> None:
    calibrator = PercentileScoreCalibrator.fit([1.0, 2.0, 10.0, 12.0])
    assert calibrator.calibrate(2.0) == 0.5
    assert calibrator.calibrate(2.0) < calibrator.calibrate(12.0)


@pytest.mark.parametrize(
    "calibrator",
    [
        IdentityScoreCalibrator(),
        CosineScoreCalibrator(),
        RobustMinMaxScoreCalibrator(0.0, 10.0),
        PercentileScoreCalibrator.fit([0.0, 1.0, 2.0]),
        LogisticScoreCalibrator(1.0, 0.0),
        IsotonicScoreCalibrator.fit([0.0, 1.0, 2.0], [0, 0, 1]),
    ],
)
def test_calibrators_never_return_nan_or_inf(calibrator) -> None:
    value = calibrator.calibrate(0.5)
    assert math.isfinite(value) and 0 <= value <= 1


def test_supervised_calibrators_fit_only_explicit_samples() -> None:
    logistic = LogisticScoreCalibrator.fit([0.0, 0.2, 0.8, 1.0], [0, 0, 1, 1])
    isotonic = IsotonicScoreCalibrator.fit([0.0, 0.2, 0.8, 1.0], [0, 0, 1, 1])
    assert logistic.calibrate(0.9) > logistic.calibrate(0.1)
    assert isotonic.calibrate(0.9) >= isotonic.calibrate(0.1)


@pytest.mark.parametrize(
    "query",
    ["TCP", "RFC 793", "Figure 3", "Section 2.1", "BKT", "2024"],
)
def test_exact_lexical_queries_receive_more_confidence(query: str) -> None:
    results = [RankedItem("a", 12.0), RankedItem("b", 7.0)]
    calibrator = RobustMinMaxScoreCalibrator(0.0, 20.0)
    ordinary = lexical_confidence("为什么网络有时比较慢", results, calibrator)
    assert lexical_confidence(query, results, calibrator) > ordinary


def test_reranker_is_disabled_by_default_and_lambda_one_restores_prior() -> None:
    assert RetrievalConfig().reranker_enabled is False
    prior = [RankedItem("a", 0.8), RankedItem("b", 0.7)]
    scores = {"a": 0.0, "b": 1.0}
    assert blend_retrieval_and_reranker(prior, scores, 1.0) == prior
    assert blend_retrieval_and_reranker(prior, scores, 0.8)[0].chunk_id == "a"


def test_multi_chunk_aggregation_supports_max_and_mean() -> None:
    assert aggregate_chunk_scores([0.1, 0.9, 0.2], "max") == 0.9
    assert aggregate_chunk_scores([0.1, 0.9, 0.2], "mean") == pytest.approx(0.4)


class _FailingTranslator:
    def translate(self, query: str) -> str | None:
        raise RuntimeError("offline")


def test_translation_failure_falls_back_without_disabling_expansion() -> None:
    variants = RuleBasedQueryProcessor(translator=_FailingTranslator()).process("BKT")
    assert variants.translated == ""
    assert "Bayesian Knowledge Tracing" in variants.expansions
    assert variants.bm25_body_query.startswith("BKT")


def test_unicode_word_is_not_split_into_ascii_substrings() -> None:
    assert GlossaryQueryExpansion().expand("Missä Helsinki sijaitsee?") == ()


def test_expansion_translation_and_intent_are_independent() -> None:
    expansions = GlossaryQueryExpansion().expand("OS 与 BKT")
    assert expansions == ("Bayesian Knowledge Tracing", "Operating System")
    roles = RuleBasedQueryIntent().content_roles("作者、机构和参考文献")
    assert {
        ContentRole.AUTHOR_INFO,
        ContentRole.AFFILIATION,
        ContentRole.REFERENCE,
    } <= roles
