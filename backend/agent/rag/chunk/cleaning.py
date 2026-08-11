"""RAG 检索文本清洁和内容角色分类，不修改 DocIR 原始事实。"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass

from backend.agent.DocIR.core.elements import ElementBase, FigureElement, TableElement
from backend.agent.DocIR.core.enums import ElementRole

from .models import ContentRole, DEFAULT_RETRIEVAL_ROLES

_HTML_TAG = re.compile(
    r"</?(?:span|div|p|br|strong|em|sup|sub|table|thead|tbody|tr|th|td|ul|ol|li)\b[^>]*>",
    re.IGNORECASE,
)
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_HORIZONTAL_SPACE = re.compile(r"[^\S\r\n]+")
_MANY_NEWLINES = re.compile(r"\n\s*\n(?:\s*\n)+")
_LINE_BREAK_HYPHEN = re.compile(r"(?<=[A-Za-z])-\s*\n\s*(?=[a-z])")
_SPACED_MATH_WORD = re.compile(
    r"(\\(?:mathrm|operatorname)\s*\{)\s*((?:[A-Za-z]\s+){2,}[A-Za-z])\s*(\})"
)

_REFERENCE_HEADING = re.compile(
    r"^(?:references?|bibliography|参考文献|引用文献)(?:\s|$)", re.IGNORECASE
)
_APPENDIX_HEADING = re.compile(r"^(?:appendix|附录)(?:\s|$)", re.IGNORECASE)
_CITATION_PREFIX = re.compile(
    r"^(?:recommended citation|how to cite|cite as|引用格式)\s*[:：]",
    re.IGNORECASE,
)
_AUTHOR_PREFIX = re.compile(r"^(?:authors?|作者)\s*[:：]", re.IGNORECASE)
_METADATA_PREFIX = re.compile(
    r"^(?:title|标题|keywords?|published|publication date|date|doi|isbn|issn)\s*[:：—-]",
    re.IGNORECASE,
)
_AFFILIATION_HINT = re.compile(
    r"(?:university|institute|department|laboratory|college|school of|faculty|research group|computing group|center for|centre for|大学|学院|研究所|实验室)",
    re.IGNORECASE,
)
_AFFILIATION_LINE = re.compile(
    r"^(?:\d+[\s,*†‡]*)?(?:department|institute|laboratory|college|school of|大学|学院|研究所|实验室)\b",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_ADDRESS_LINE = re.compile(
    r"(?:\b\d+\s+[A-Za-z .'-]+(?:ave|avenue|street|st|road|rd)\b|\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b|^(?:united kingdom|united states|usa|china|india|morocco)$)",
    re.IGNORECASE,
)
_METADATA_HEADING = re.compile(
    r"^(?:keywords?|ccs concepts|author statement|publication metadata)$",
    re.IGNORECASE,
)
_DATE_LINE = re.compile(
    r"^(?:(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+\d{4}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})$",
    re.IGNORECASE,
)
_NAME_TOKEN = re.compile(r"(?:[A-Z][A-Za-z'’-]*|[A-Z]\.|and|&|\d+)")

# 这里只识别整条 Element 都是标签的高置信模式。描述性图注必须继续保留。
_FIGURE_NUMBER_ONLY = re.compile(
    r"^(?:图|fig(?:ure)?\.?)\s*[A-Za-z]?\s*\d+"
    r"(?:\s*[-–—.]\s*\d+)+(?:\s*[（(]?\s*续\s*[)）]?)?$",
    re.IGNORECASE,
)
_FIGURE_NUMERIC_UNIT_ONLY = re.compile(
    r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)\s*"
    r"(?:比特|位|字节|bits?|bytes?|[kmgt]i?b|hz|khz|mhz|ghz)$",
    re.IGNORECASE,
)
_BOOK_EDITION_ONLY = re.compile(
    r"^(?:原书\s*)?第\s*[0-9一二三四五六七八九十百]+\s*版$"
)
_CHAPTER_NAVIGATION_ONLY = re.compile(
    r"^第\s*[0-9一二三四五六七八九十百]+\s*[章节篇部]$"
)


@dataclass(frozen=True)
class RetrievalText:
    """同一事实的原始文本、检索文本与检索角色。"""

    raw_text: str
    normalized_text: str
    content_role: ContentRole
    retrieval_enabled: bool


def normalize_retrieval_text(text: str) -> str:
    """只执行高置信规范化；调用方仍须单独保存原文。"""

    value = unicodedata.normalize("NFKC", text)
    value = html.unescape(value)
    value = _HTML_TAG.sub(" ", value)
    value = _INVISIBLE.sub("", value)
    value = _LINE_BREAK_HYPHEN.sub("", value)

    def collapse_math_word(match: re.Match[str]) -> str:
        return f"{match.group(1)}{''.join(match.group(2).split())}{match.group(3)}"

    value = _SPACED_MATH_WORD.sub(collapse_math_word, value)
    lines = [_HORIZONTAL_SPACE.sub(" ", line).strip() for line in value.splitlines()]
    value = "\n".join(lines)
    value = _MANY_NEWLINES.sub("\n\n", value)
    return value.strip()


@dataclass(frozen=True)
class RetrievalCleaner:
    """以保守规则为 Element 标注检索角色并产生规范化副本。"""

    def clean(
        self,
        element: ElementBase,
        raw_text: str,
        section_path: tuple[str, ...],
    ) -> RetrievalText:
        normalized = normalize_retrieval_text(raw_text)
        role = self.classify(element, normalized, section_path)
        return RetrievalText(
            raw_text=raw_text,
            normalized_text=normalized,
            content_role=role,
            retrieval_enabled=role in DEFAULT_RETRIEVAL_ROLES,
        )

    @staticmethod
    def standalone_exclusion_reason(
        element: ElementBase,
        text: str,
        *,
        filter_standalone_figure_labels: bool,
        filter_navigation_labels: bool,
    ) -> str | None:
        """返回高置信独立标签的 disposition reason。"""

        normalized = normalize_retrieval_text(text)
        if not normalized or "\n" in normalized:
            return None
        if filter_standalone_figure_labels and isinstance(element, FigureElement):
            if _FIGURE_NUMBER_ONLY.fullmatch(normalized):
                return "figure_label_only"
            if _FIGURE_NUMERIC_UNIT_ONLY.fullmatch(normalized):
                return "figure_label_only"
        if filter_navigation_labels and (
            _BOOK_EDITION_ONLY.fullmatch(normalized)
            or _CHAPTER_NAVIGATION_ONLY.fullmatch(normalized)
        ):
            return "navigation_label_only"
        return None

    @staticmethod
    def classify(
        element: ElementBase,
        raw_text: str,
        section_path: tuple[str, ...],
    ) -> ContentRole:
        if isinstance(element, TableElement):
            return ContentRole.TABLE
        if isinstance(element, FigureElement) or element.role in {
            ElementRole.CAPTION,
            ElementRole.VLM_DESCRIPTION,
        }:
            return ContentRole.FIGURE_CAPTION

        section_title = section_path[-1].strip() if section_path else ""
        source_type = (element.source_type or "").strip().lower()
        text = raw_text.strip()
        if source_type in {"ref_text", "reference", "bibliography"}:
            return ContentRole.REFERENCE
        if _REFERENCE_HEADING.match(section_title):
            return ContentRole.REFERENCE
        if _APPENDIX_HEADING.match(section_title):
            return ContentRole.APPENDIX
        if _METADATA_HEADING.match(section_title):
            return ContentRole.METADATA
        if _CITATION_PREFIX.match(text):
            return ContentRole.CITATION_INFO
        if _AUTHOR_PREFIX.match(text) or source_type in {"author", "authors"}:
            return ContentRole.AUTHOR_INFO
        if _METADATA_PREFIX.match(text) or source_type in {
            "title",
            "date",
            "doi",
            "metadata",
        }:
            return ContentRole.METADATA
        if element.document_order <= 40 and _DATE_LINE.match(text):
            return ContentRole.METADATA
        if source_type in {"affiliation", "address"}:
            return ContentRole.AFFILIATION
        if _AFFILIATION_LINE.search(text):
            return ContentRole.AFFILIATION
        if element.document_order <= 40 and (
            _EMAIL.search(text)
            or _ADDRESS_LINE.search(text)
            or (
                _AFFILIATION_HINT.search(text)
                and len(text.split()) <= 30
                and not text.rstrip().endswith((".", "?", "!"))
            )
        ):
            return ContentRole.AFFILIATION
        if element.document_order <= 40 and RetrievalCleaner._looks_like_author_line(
            text
        ):
            return ContentRole.AUTHOR_INFO
        return ContentRole.BODY

    @staticmethod
    def _looks_like_author_line(text: str) -> bool:
        """只识别文档前部的严格拉丁姓名行，避免把普通短句当作者。"""

        if not 2 <= len(text.split()) <= 16 or any(mark in text for mark in "?!:；。"):
            return False
        cleaned = re.sub(r"[,;*†‡()]", " ", text)
        tokens = cleaned.split()
        if len(tokens) < 2:
            return False
        matched = sum(bool(_NAME_TOKEN.fullmatch(token)) for token in tokens)
        return matched / len(tokens) >= 0.8
