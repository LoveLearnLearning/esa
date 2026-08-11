# backend/agent/rag/retrieval/__init__.py

"""

这个文件干什么：混合召回、融合、重排、上下文和最终检索编排。

直白点说就是：这里把一次检索需要的召回、合并、重排、上下文和结果组装模块归在一起。

混合召回、融合、重排、上下文和最终检索编排。
"""

from .calibration import (
    CosineScoreCalibrator,
    IdentityScoreCalibrator,
    IsotonicScoreCalibrator,
    LogisticScoreCalibrator,
    PercentileScoreCalibrator,
    RobustMinMaxScoreCalibrator,
    ScoreCalibrator,
)
from .contracts import RetrievalConfig
from .query import (
    GlossaryQueryExpansion,
    NullQueryTranslator,
    QueryExpander,
    QueryIntent,
    QueryProcessor,
    QueryTranslator,
    QueryVariants,
    RuleBasedQueryIntent,
    RuleBasedQueryProcessor,
    StaticQueryTranslator,
)
from .service import RetrievalService

__all__ = [
    "CosineScoreCalibrator",
    "GlossaryQueryExpansion",
    "IdentityScoreCalibrator",
    "IsotonicScoreCalibrator",
    "LogisticScoreCalibrator",
    "NullQueryTranslator",
    "PercentileScoreCalibrator",
    "QueryExpander",
    "QueryIntent",
    "QueryProcessor",
    "QueryTranslator",
    "QueryVariants",
    "RobustMinMaxScoreCalibrator",
    "RetrievalConfig",
    "RetrievalService",
    "RuleBasedQueryIntent",
    "RuleBasedQueryProcessor",
    "ScoreCalibrator",
    "StaticQueryTranslator",
]
