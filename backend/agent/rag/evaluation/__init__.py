# backend/agent/rag/evaluation/__init__.py

"""

这个文件干什么：检索指标、参考评测与真实模型基准。

直白点说就是：把检索评测指标和基准测试入口集中导出。

检索指标、参考评测与真实模型基准。
"""

from .answer_quality import (
    AnswerFacet,
    AnswerQualityBenchmark,
    AnswerQualityCase,
    AnswerQualityMetrics,
    EvidenceJudgment,
    UnjudgedRankingError,
    evaluate_answer_quality,
    evaluate_frozen_pool,
    load_answer_quality_benchmark,
    load_answer_quality_cases,
)
from .metrics import EvaluationCase, RetrievalMetrics, evaluate_layers

__all__ = [
    "AnswerFacet",
    "AnswerQualityBenchmark",
    "AnswerQualityCase",
    "AnswerQualityMetrics",
    "EvaluationCase",
    "EvidenceJudgment",
    "RetrievalMetrics",
    "UnjudgedRankingError",
    "evaluate_answer_quality",
    "evaluate_frozen_pool",
    "evaluate_layers",
    "load_answer_quality_benchmark",
    "load_answer_quality_cases",
]
