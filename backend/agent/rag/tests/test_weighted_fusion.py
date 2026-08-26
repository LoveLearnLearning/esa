# backend/agent/rag/tests/test_weighted_fusion.py

"""Dense 主导融合、词法 gate、串行 Reranker 与查询职责拆分测试。"""

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
    rerank_by_score,
)


def _routes() -> dict[str, list[RankedItem]]:
    """处理 `_routes` 相关逻辑。"""
    return {
        "dense": [RankedItem("dense-a", 0.9), RankedItem("shared", 0.8)],
        "bm25_body": [RankedItem("body-only", 12.0), RankedItem("shared", 8.0)],
        "bm25_heading": [RankedItem("heading-only", 9.0)],
    }


def _calibrators():
    """处理 `_calibrators` 相关逻辑。"""
    return {
        "dense": CosineScoreCalibrator(),
        "bm25_body": RobustMinMaxScoreCalibrator(0.0, 20.0),
        "bm25_heading": RobustMinMaxScoreCalibrator(0.0, 20.0),
    }


def test_score_fusion_preserves_raw_scores_ranks_and_missing_routes() -> None:
    """验证 `score_fusion_preserves_raw_scores_ranks_and_missing_routes` 场景。"""
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
    """验证 `dense_only_is_exactly_alpha_one_and_reproducible` 场景。"""
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
    """验证 `global_percentile_does_not_promote_weak_query_top_to_one` 场景。"""
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
    """验证 `calibrators_never_return_nan_or_inf` 场景。"""
    value = calibrator.calibrate(0.5)
    assert math.isfinite(value) and 0 <= value <= 1


def test_supervised_calibrators_fit_only_explicit_samples() -> None:
    """验证 `supervised_calibrators_fit_only_explicit_samples` 场景。"""
    logistic = LogisticScoreCalibrator.fit([0.0, 0.2, 0.8, 1.0], [0, 0, 1, 1])
    isotonic = IsotonicScoreCalibrator.fit([0.0, 0.2, 0.8, 1.0], [0, 0, 1, 1])
    assert logistic.calibrate(0.9) > logistic.calibrate(0.1)
    assert isotonic.calibrate(0.9) >= isotonic.calibrate(0.1)


@pytest.mark.parametrize(
    "query",
    ["TCP", "RFC 793", "Figure 3", "Section 2.1", "ABC.1", "BKT", "2024"],
)
def test_exact_lexical_queries_receive_more_confidence(query: str) -> None:
    """验证 `exact_lexical_queries_receive_more_confidence` 场景。"""
    results = [RankedItem("a", 12.0), RankedItem("b", 7.0)]
    calibrator = RobustMinMaxScoreCalibrator(0.0, 20.0)
    ordinary = lexical_confidence("为什么网络有时比较慢", results, calibrator)
    assert lexical_confidence(query, results, calibrator) > ordinary


def test_reranker_is_disabled_by_default_and_reranking_ignores_fusion_scale() -> None:
    """验证默认关闭 Reranker，显式重排仍不混入 fusion 分数。"""
    assert RetrievalConfig().reranker_enabled is False
    prior = [RankedItem("a", 1000.0), RankedItem("b", 0.001)]
    scores = {"a": 0.0, "b": 1.0}
    assert [item.chunk_id for item in rerank_by_score(prior, scores)] == ["b", "a"]


def test_multi_chunk_aggregation_supports_max_and_mean() -> None:
    """验证 `multi_chunk_aggregation_supports_max_and_mean` 场景。"""
    assert aggregate_chunk_scores([0.1, 0.9, 0.2], "max") == 0.9
    assert aggregate_chunk_scores([0.1, 0.9, 0.2], "mean") == pytest.approx(0.4)


class _FailingTranslator:
    """封装 `_FailingTranslator` 的状态与行为。"""
    def translate(self, query: str) -> str | None:
        """处理 `translate` 相关逻辑。"""
        raise RuntimeError("offline")


def test_translation_failure_falls_back_without_disabling_expansion() -> None:
    """验证 `translation_failure_falls_back_without_disabling_expansion` 场景。"""
    variants = RuleBasedQueryProcessor(translator=_FailingTranslator()).process("BKT")
    assert variants.translated == ""
    assert "Bayesian Knowledge Tracing" in variants.expansions
    assert variants.bm25_body_query.startswith("BKT")


def test_unicode_word_is_not_split_into_ascii_substrings() -> None:
    """验证 `unicode_word_is_not_split_into_ascii_substrings` 场景。"""
    assert GlossaryQueryExpansion().expand("Missä Helsinki sijaitsee?") == ()


def test_expansion_translation_and_intent_are_independent() -> None:
    """验证 `expansion_translation_and_intent_are_independent` 场景。"""
    expansions = GlossaryQueryExpansion().expand("OS 与 BKT")
    assert expansions == ("Bayesian Knowledge Tracing", "Operating System")
    roles = RuleBasedQueryIntent().content_roles("作者、机构和参考文献")
    assert {
        ContentRole.AUTHOR_INFO,
        ContentRole.AFFILIATION,
        ContentRole.REFERENCE,
    } <= roles
