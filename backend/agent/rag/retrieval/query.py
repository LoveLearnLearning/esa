# backend/agent/rag/retrieval/query.py

"""职责分离、失败可降级的查询翻译、术语扩展与意图路由。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from ..chunk import ContentRole, DEFAULT_RETRIEVAL_ROLES


class QueryTranslator(Protocol):
    """把查询翻译成英文；不可用时返回 ``None`` 或抛出异常。"""

    def translate(self, query: str) -> str | None:
        """处理 `translate` 相关逻辑。"""
        ...


class QueryExpander(Protocol):
    """返回缩写或专业术语对应的附加检索短语。"""

    def expand(self, query: str) -> tuple[str, ...]:
        """处理 `expand` 相关逻辑。"""
        ...


class QueryIntent(Protocol):
    """根据显式用户意图开放默认被抑制的内容角色。"""

    def content_roles(self, query: str) -> frozenset[ContentRole]:
        """处理 `content_roles` 相关逻辑。"""
        ...


@dataclass(frozen=True)
class NullQueryTranslator:
    """不依赖外部模型的默认翻译器。"""

    def translate(self, query: str) -> str | None:
        """处理 `translate` 相关逻辑。"""
        return None


@dataclass(frozen=True)
class StaticQueryTranslator:
    """用于人工 gold benchmark 或部署侧词典的确定性翻译器。"""

    translations: dict[str, str]

    def translate(self, query: str) -> str | None:
        """处理 `translate` 相关逻辑。"""
        return self.translations.get(query)


_DEFAULT_EXPANSIONS = (
    ("BKT", "Bayesian Knowledge Tracing"),
    ("OS", "Operating System"),
    ("贝叶斯知识追踪", "Bayesian Knowledge Tracing"),
    ("猜测概率", "guess probability"),
    ("失误概率", "slip probability"),
    ("掌握概率", "mastery probability"),
    ("掌握度", "mastery"),
    ("知识追踪", "knowledge tracing"),
    ("先修关系", "prerequisite relationship"),
    ("间隔复习", "spaced repetition"),
    ("遗忘曲线", "forgetting curve"),
    ("多智能体", "multi-agent"),
    ("学习者状态", "learner state"),
)


def _contains_term(query: str, term: str) -> bool:
    """处理 `_contains_term` 相关逻辑。"""
    if term.isascii():
        # Python 的 \w 具有 Unicode 语义，因此不会从 ``Missä`` 中截出 ``Miss``。
        return (
            re.search(rf"(?<!\w){re.escape(term)}(?!\w)", query, re.IGNORECASE)
            is not None
        )
    return term in query


@dataclass(frozen=True)
class GlossaryQueryExpansion:
    """只扩展明确命中的完整术语，不从 Unicode 单词截取 ASCII 子串。"""

    expansions: tuple[tuple[str, str], ...] = _DEFAULT_EXPANSIONS

    def expand(self, query: str) -> tuple[str, ...]:
        """处理 `expand` 相关逻辑。"""
        return tuple(
            dict.fromkeys(
                expansion
                for term, expansion in self.expansions
                if _contains_term(query, term)
            )
        )


_REFERENCE_INTENT = re.compile(
    r"(?:参考文献|引用了|引用哪些|文献列表|references?|bibliography|citations?)",
    re.IGNORECASE,
)
_AUTHOR_INTENT = re.compile(
    r"(?:作者|谁写的|所属机构|单位|affiliations?|authors?)", re.IGNORECASE
)
_CITATION_INTENT = re.compile(
    r"(?:推荐引用|引用格式|如何引用|recommended citation|how to cite|cite as)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RuleBasedQueryIntent:
    """只负责作者、机构、引用和 metadata 的结构化路由。"""

    def content_roles(self, query: str) -> frozenset[ContentRole]:
        """处理 `content_roles` 相关逻辑。"""
        roles = set(DEFAULT_RETRIEVAL_ROLES)
        if _REFERENCE_INTENT.search(query):
            roles.add(ContentRole.REFERENCE)
        if _AUTHOR_INTENT.search(query):
            roles.update({ContentRole.AUTHOR_INFO, ContentRole.AFFILIATION})
        if _CITATION_INTENT.search(query):
            roles.update({ContentRole.CITATION_INFO, ContentRole.METADATA})
        return frozenset(roles)


@dataclass(frozen=True)
class QueryVariants:
    """三个独立处理阶段的结果及 BM25 所需组合视图。"""

    original: str
    translated: str = ""
    expansions: tuple[str, ...] = ()
    content_roles: frozenset[ContentRole] = DEFAULT_RETRIEVAL_ROLES

    @property
    def keywords(self) -> tuple[str, ...]:
        """兼容旧调用方；新代码应使用更明确的 ``expansions``。"""

        return self.expansions

    @property
    def bm25_body_query(self) -> str:
        """处理 `bm25_body_query` 相关逻辑。"""
        return " ".join(
            dict.fromkeys(
                part
                for part in (self.original, self.translated, *self.expansions)
                if part.strip()
            )
        )

    @property
    def bm25_heading_query(self) -> str:
        """处理 `bm25_heading_query` 相关逻辑。"""
        parts = (self.translated, *self.expansions)
        query = " ".join(dict.fromkeys(part for part in parts if part.strip()))
        return query or self.original


class QueryProcessor(Protocol):
    """定义 `QueryProcessor` 组件协议。"""
    def process(self, query: str) -> QueryVariants:
        """处理 `process` 相关数据。"""
        ...


@dataclass(frozen=True)
class RuleBasedQueryProcessor:
    """组合三个单一职责组件；翻译失败只降级该能力。"""

    translator: QueryTranslator = field(default_factory=NullQueryTranslator)
    expander: QueryExpander = field(default_factory=GlossaryQueryExpansion)
    intent: QueryIntent = field(default_factory=RuleBasedQueryIntent)

    def process(self, query: str) -> QueryVariants:
        """处理 `process` 相关数据。"""
        try:
            translated = (self.translator.translate(query) or "").strip()
        except Exception:
            translated = ""
        expansions = self.expander.expand(query)
        roles = self.intent.content_roles(query)
        return QueryVariants(query, translated, expansions, roles)
