"""Pre-retrieval policy for the model-facing retrieval context view."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class MetadataProfile(str, Enum):
    """Small, stable set of model-facing retrieval views."""

    MINIMAL = "MINIMAL"
    SOURCE = "SOURCE"
    LOCATION = "LOCATION"
    FULL = "FULL"


@dataclass(frozen=True, slots=True)
class RetrievalRouteInput:
    """Trusted user intent available before any retrieval tool executes."""

    current_user_message: str
    recent_user_messages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """Auditable output shared by rule-based and future trained routers."""

    profile: MetadataProfile
    router_type: str
    router_version: str
    reason_code: str
    matched_rule: str | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class RetrievalProjectionContext:
    """One turn's immutable projection policy carried by its tool executor."""

    enabled: bool
    route_input: RetrievalRouteInput
    decision: RouteDecision | None = None
    fallback_reason: str | None = None


class ContextRouter(Protocol):
    """Replaceable router seam; implementations must not mutate turn state."""

    def route(self, route_input: RetrievalRouteInput) -> RouteDecision:
        ...


class RuleBasedContextRouter:
    """High-precision bootstrap rules with MINIMAL as the default."""

    router_type = "rule"
    router_version = "metadata_projection.rule.v1"

    _negative_markers = ("不用", "不要", "无需", "无须", "不必", "别", "无需提供")
    _full = (
        "metadata",
        "元数据",
        "chunk_id",
        "document_id",
        "retrieval_score",
        "rerank_score",
        "bm25",
        "dense",
        "fusion",
        "trace",
        "bbox",
        "parser",
    )
    _full_contextual = ("score", "分数")
    _debug_context = ("chunk", "检索", "retrieval", "rerank", "metadata", "元数据", "完整")
    _location = (
        "哪一页",
        "第几页",
        "页码",
        "哪一章",
        "哪一节",
        "哪个章节",
        "什么位置",
        "在哪里提到",
        "定位",
        "locator",
        "page",
    )
    _source = (
        "出处",
        "来源",
        "引用",
        "哪篇论文",
        "哪篇文档",
        "哪本书",
        "哪份文档",
        "谁提出的",
        "谁提出",
        "谁说的",
        "谁说",
        "参考文献",
        "来自哪里",
        "作者",
        "source",
        "citation",
    )

    @classmethod
    def _unnegated_match(
        cls,
        text: str,
        keywords: tuple[str, ...],
    ) -> str | None:
        """Return the first keyword not locally governed by a negation."""

        for keyword in keywords:
            start = 0
            while True:
                index = text.find(keyword, start)
                if index < 0:
                    break
                boundary = max(
                    (text.rfind(marker, 0, index) for marker in "，,。；;！？!?\n"),
                    default=-1,
                )
                prefix = text[max(boundary + 1, index - 10) : index]
                if not any(marker in prefix for marker in cls._negative_markers):
                    return keyword
                start = index + len(keyword)
        return None

    def route(self, route_input: RetrievalRouteInput) -> RouteDecision:
        text = route_input.current_user_message.casefold().strip()
        contextual_debug = self._unnegated_match(text, self._full_contextual)
        if contextual_debug is not None and any(
            marker in text for marker in self._debug_context
        ):
            return RouteDecision(
                profile=MetadataProfile.FULL,
                router_type=self.router_type,
                router_version=self.router_version,
                reason_code="explicit_debug_metadata",
                matched_rule=contextual_debug,
                confidence=1.0,
            )
        for profile, reason, keywords in (
            (MetadataProfile.FULL, "explicit_debug_metadata", self._full),
            (MetadataProfile.LOCATION, "explicit_location", self._location),
            (MetadataProfile.SOURCE, "explicit_source", self._source),
        ):
            matched = self._unnegated_match(text, keywords)
            if matched is not None:
                return RouteDecision(
                    profile=profile,
                    router_type=self.router_type,
                    router_version=self.router_version,
                    reason_code=reason,
                    matched_rule=matched,
                    confidence=1.0,
                )
        return RouteDecision(
            profile=MetadataProfile.MINIMAL,
            router_type=self.router_type,
            router_version=self.router_version,
            reason_code="default_minimal",
            confidence=1.0,
        )
