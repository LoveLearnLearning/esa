# backend/agent/rag/retrieval/calibration.py

"""可复现的检索分数校准器，不依赖具体索引或模型实现。"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class ScoreCalibrator(Protocol):
    """把某一路原始分数映射到有限的 ``[0, 1]`` 区间。"""

    def calibrate(self, score: float) -> float:
        """处理 `calibrate` 相关逻辑。"""
        ...


def _finite(score: float) -> float:
    """处理 `_finite` 相关逻辑。"""
    value = float(score)
    if not math.isfinite(value):
        raise ValueError("score must be finite")
    return value


def _unit(value: float) -> float:
    """处理 `_unit` 相关逻辑。"""
    return min(1.0, max(0.0, value))


@dataclass(frozen=True)
class IdentityScoreCalibrator:
    """保留已经处于 ``[0, 1]`` 的分数，并对边界做显式裁剪。"""

    def calibrate(self, score: float) -> float:
        """处理 `calibrate` 相关逻辑。"""
        return _unit(_finite(score))


@dataclass(frozen=True)
class CosineScoreCalibrator:
    """把 cosine 的 ``[-1, 1]`` 映射到 ``[0, 1]``。"""

    def calibrate(self, score: float) -> float:
        """处理 `calibrate` 相关逻辑。"""
        return _unit((_finite(score) + 1.0) / 2.0)


@dataclass(frozen=True)
class RobustMinMaxScoreCalibrator:
    """按显式给定的稳健上下界缩放；上下界必须来自独立统计。"""

    lower: float
    upper: float

    def __post_init__(self) -> None:
        """完成实例初始化后的校验与派生字段构建。"""
        if not math.isfinite(self.lower) or not math.isfinite(self.upper):
            raise ValueError("calibration bounds must be finite")
        if self.upper <= self.lower:
            raise ValueError("upper calibration bound must exceed lower bound")

    def calibrate(self, score: float) -> float:
        """处理 `calibrate` 相关逻辑。"""
        return _unit((_finite(score) - self.lower) / (self.upper - self.lower))

    @classmethod
    def fit(
        cls,
        scores: Sequence[float],
        *,
        lower_quantile: float = 0.05,
        upper_quantile: float = 0.95,
    ) -> "RobustMinMaxScoreCalibrator":
        """处理 `fit` 相关逻辑。

        Args:
            scores: Sequence[float] => `scores` 参数。
            lower_quantile: float => `lower_quantile` 参数。
            upper_quantile: float => `upper_quantile` 参数。

        Returns:
            'RobustMinMaxScoreCalibrator' => 处理结果。
        """
        values = sorted(_finite(score) for score in scores)
        if len(values) < 2:
            raise ValueError("at least two scores are required")
        if not 0 <= lower_quantile < upper_quantile <= 1:
            raise ValueError("invalid calibration quantiles")
        lower = values[round((len(values) - 1) * lower_quantile)]
        upper = values[round((len(values) - 1) * upper_quantile)]
        if upper <= lower:
            lower, upper = values[0], values[-1]
        if upper <= lower:
            raise ValueError("score distribution has no usable range")
        return cls(lower, upper)


@dataclass(frozen=True)
class PercentileScoreCalibrator:
    """按全局参考分布计算百分位，避免每个 query 的弱 top-1 自动变成 1。"""

    reference_scores: tuple[float, ...]

    def __post_init__(self) -> None:
        """完成实例初始化后的校验与派生字段构建。"""
        values = tuple(_finite(value) for value in self.reference_scores)
        if len(values) < 2 or values != tuple(sorted(values)):
            raise ValueError("reference_scores must contain at least two sorted values")

    @classmethod
    def fit(cls, scores: Sequence[float]) -> "PercentileScoreCalibrator":
        """处理 `fit` 相关逻辑。"""
        return cls(tuple(sorted(_finite(score) for score in scores)))

    def calibrate(self, score: float) -> float:
        """处理 `calibrate` 相关逻辑。"""
        value = _finite(score)
        right = bisect.bisect_right(self.reference_scores, value)
        return right / len(self.reference_scores)


@dataclass(frozen=True)
class LogisticScoreCalibrator:
    """可由独立 calibration split 拟合或直接加载的 Platt-style 映射。"""

    slope: float
    intercept: float

    def __post_init__(self) -> None:
        """完成实例初始化后的校验与派生字段构建。"""
        if not math.isfinite(self.slope) or not math.isfinite(self.intercept):
            raise ValueError("logistic parameters must be finite")

    def calibrate(self, score: float) -> float:
        """处理 `calibrate` 相关逻辑。"""
        logit = self.slope * _finite(score) + self.intercept
        if logit >= 0:
            return 1.0 / (1.0 + math.exp(-logit))
        exp_value = math.exp(logit)
        return exp_value / (1.0 + exp_value)

    @classmethod
    def fit(
        cls,
        scores: Sequence[float],
        labels: Sequence[int],
        *,
        learning_rate: float = 0.05,
        iterations: int = 1000,
        l2: float = 1e-4,
    ) -> "LogisticScoreCalibrator":
        """在调用方提供的独立 calibration split 上拟合二元映射。"""

        if len(scores) != len(labels) or not scores:
            raise ValueError("scores and labels must be non-empty and aligned")
        values = [_finite(score) for score in scores]
        targets = [int(label) for label in labels]
        if any(label not in (0, 1) for label in targets):
            raise ValueError("logistic labels must be binary")
        if learning_rate <= 0 or iterations <= 0 or l2 < 0:
            raise ValueError("invalid logistic fit parameters")
        slope = 0.0
        positive_rate = min(1 - 1e-6, max(1e-6, sum(targets) / len(targets)))
        intercept = math.log(positive_rate / (1.0 - positive_rate))
        for _iteration in range(iterations):
            slope_gradient = l2 * slope
            intercept_gradient = 0.0
            for score, target in zip(values, targets):
                probability = cls(slope, intercept).calibrate(score)
                error = probability - target
                slope_gradient += error * score / len(values)
                intercept_gradient += error / len(values)
            slope -= learning_rate * slope_gradient
            intercept -= learning_rate * intercept_gradient
        return cls(slope, intercept)


@dataclass(frozen=True)
class IsotonicScoreCalibrator:
    """从独立 calibration split 导出的单调分段常数映射。"""

    thresholds: tuple[float, ...]
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        """完成实例初始化后的校验与派生字段构建。"""
        if not self.thresholds or len(self.thresholds) != len(self.values):
            raise ValueError("isotonic thresholds and values must be aligned")
        if self.thresholds != tuple(sorted(self.thresholds)):
            raise ValueError("isotonic thresholds must be sorted")
        if any(not 0 <= value <= 1 for value in self.values):
            raise ValueError("isotonic values must be probabilities")
        if any(left > right for left, right in zip(self.values, self.values[1:])):
            raise ValueError("isotonic values must be non-decreasing")

    def calibrate(self, score: float) -> float:
        """处理 `calibrate` 相关逻辑。"""
        index = bisect.bisect_left(self.thresholds, _finite(score))
        return self.values[min(index, len(self.values) - 1)]

    @classmethod
    def fit(
        cls, scores: Sequence[float], labels: Sequence[int]
    ) -> "IsotonicScoreCalibrator":
        """处理 `fit` 相关逻辑。

        Args:
            scores: Sequence[float] => `scores` 参数。
            labels: Sequence[int] => `labels` 参数。

        Returns:
            'IsotonicScoreCalibrator' => 处理结果。
        """
        if len(scores) != len(labels) or not scores:
            raise ValueError("scores and labels must be non-empty and aligned")
        pairs = sorted(
            (_finite(score), int(label)) for score, label in zip(scores, labels)
        )
        if any(label not in (0, 1) for _score, label in pairs):
            raise ValueError("isotonic labels must be binary")
        blocks: list[list[float]] = []
        for score, label in pairs:
            blocks.append([score, score, float(label), 1.0])
            while (
                len(blocks) >= 2
                and blocks[-2][2] / blocks[-2][3] > blocks[-1][2] / blocks[-1][3]
            ):
                right = blocks.pop()
                left = blocks.pop()
                blocks.append(
                    [left[0], right[1], left[2] + right[2], left[3] + right[3]]
                )
        return cls(
            tuple(block[1] for block in blocks),
            tuple(block[2] / block[3] for block in blocks),
        )
