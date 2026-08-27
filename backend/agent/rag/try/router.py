"""A deliberately narrow, replaceable query router for the experiment."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Profile(str, Enum):
    MINIMAL = "MINIMAL"
    SOURCE = "SOURCE"
    LOCATION = "LOCATION"
    FULL = "FULL"


@dataclass(frozen=True)
class RouteDecision:
    profile: Profile
    need_provenance: bool
    reason: str


class ContextRouter:
    def route(self, query: str) -> RouteDecision:
        raise NotImplementedError


class RuleBasedRouter(ContextRouter):
    """High precision rules; intentionally conservative and easy to replace."""

    _negative = ("不用告诉我出处", "无需出处", "不需要出处", "不要来源", "不用来源")
    _full = ("完整 metadata", "完整元数据", "检索 score", "检索分数", "debug", "调试")
    _location = ("哪一页", "页码", "第几页", "定位", "位置", "locator", "page")
    _source = ("出处", "来源", "引用", "哪篇文档", "哪份文档", "原文", "来自哪里", "参考文献", "作者", "谁提出")

    def route(self, query: str) -> RouteDecision:
        text = query.casefold().strip()
        if any(token.casefold() in text for token in self._negative):
            return RouteDecision(Profile.MINIMAL, False, "explicitly_no_provenance")
        if any(token.casefold() in text for token in self._full):
            return RouteDecision(Profile.FULL, True, "explicit_debug_or_score_request")
        if any(token.casefold() in text for token in self._location):
            return RouteDecision(Profile.LOCATION, True, "explicit_location_request")
        if any(token.casefold() in text for token in self._source):
            return RouteDecision(Profile.SOURCE, True, "explicit_source_request")
        return RouteDecision(Profile.MINIMAL, False, "default_answer")

