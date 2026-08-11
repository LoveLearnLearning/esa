# backend/agent/rag/chunk/fragments.py

"""

这个文件干什么：从 DocIR Element 构造带不可变证据的 Chunk 草稿片段。

直白点说就是：先把每个 DocIR 元素变成带文字和出处的小片段，供后面的 Chunk 拼装使用。

从 DocIR Element 构造带不可变证据的 Chunk 草稿片段。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

from backend.agent.DocIR.core.document import Document
from backend.agent.DocIR.core.elements import ElementBase, ListElement, TableElement
from backend.agent.DocIR.core.enums import TextOrigin
from backend.agent.DocIR.core.text import TextLayer

from .models import ChunkConfig, ChunkEvidence, canonical_sha256
from .cleaning import RetrievalCleaner, RetrievalText
from .models import ContentRole
from .table import table_text_groups
from .text import split_text_spans


@dataclass(frozen=True)
class Fragment:
    """一个不可再合并证据边界的检索文本片段。"""

    element_id: str
    kind: str
    section_id: str
    section_path: tuple[str, ...]
    text: str
    evidence: ChunkEvidence
    content_role: ContentRole
    retrieval_enabled: bool
    whole_element: bool
    table: bool = False


@dataclass
class Draft:
    """同一章节内准备物化为 Chunk 的有序片段。"""

    section_id: str
    section_path: tuple[str, ...]
    fragments: list[Fragment]

    @property
    def body(self) -> str:
        """返回用于 BM25 正文和上下文的组合文本。"""

        return "\n\n".join(item.text for item in self.fragments)

    @property
    def content_role(self) -> ContentRole:
        """返回草稿统一的检索角色。"""

        roles = {item.content_role for item in self.fragments}
        if len(roles) != 1:
            raise ValueError("一个 Draft 不能混合多个 content role")
        return next(iter(roles))

    @property
    def retrieval_enabled(self) -> bool:
        return all(item.retrieval_enabled for item in self.fragments)


def primary_text_layer(element: ElementBase) -> TextLayer | None:
    """返回 Element 声明的主文本层。"""

    if element.text is None:
        return None
    return next(
        (
            layer
            for layer in element.text.layers
            if layer.text_layer_id == element.text.primary_layer_id
        ),
        None,
    )


@dataclass(frozen=True)
class ElementFragmentFactory:
    """负责 Element 文本选择、位置映射和证据生成。"""

    document: Document
    config: ChunkConfig
    cleaner: RetrievalCleaner = field(default_factory=RetrievalCleaner)

    def build(
        self,
        element: ElementBase,
        section_id: str,
        section_path: tuple[str, ...],
    ) -> list[Fragment]:
        """按 Element 类型选择普通文本或表格构造策略。"""

        if isinstance(element, TableElement):
            return self._table_fragments(element, section_id, section_path)
        return self._normal_fragments(element, section_id, section_path)

    def _normal_fragments(
        self,
        element: ElementBase,
        section_id: str,
        section_path: tuple[str, ...],
    ) -> list[Fragment]:
        """从主文本、列表项或公式 LaTeX 构造普通片段。"""

        layer = primary_text_layer(element)
        if layer and layer.text.strip():
            return self._text_fragments(
                element,
                section_id,
                section_path,
                layer.text,
                "primary_text_span",
                keep_offsets=True,
            )
        if isinstance(element, ListElement) and element.items:
            source = "\n".join(item.strip() for item in element.items if item.strip())
            derivation: Literal["list_items", "formula_latex"] = "list_items"
        elif element.kind == "formula" and getattr(element, "latex", None):
            source = element.latex.strip()
            derivation = "formula_latex"
        else:
            return []
        return self._text_fragments(
            element,
            section_id,
            section_path,
            source,
            derivation,
            keep_offsets=False,
        )

    def _text_fragments(
        self,
        element: ElementBase,
        section_id: str,
        section_path: tuple[str, ...],
        source: str,
        derivation: Literal["primary_text_span", "list_items", "formula_latex"],
        *,
        keep_offsets: bool,
    ) -> list[Fragment]:
        """切分文本并为每个跨度生成一条证据。"""

        spans = split_text_spans(
            source,
            self.config.max_chars,
            min_chars=self.config.min_chars,
            overlap_sentences=self.config.fragment_overlap_sentences,
        )
        fitted: list[tuple[str, int, int, RetrievalText]] = []
        for raw_text, start, end in spans:
            pending = [(raw_text, start, end)]
            while pending:
                candidate, candidate_start, candidate_end = pending.pop(0)
                cleaned = self.cleaner.clean(element, candidate, section_path)
                if len(cleaned.normalized_text) <= self.config.max_chars:
                    fitted.append(
                        (candidate, candidate_start, candidate_end, cleaned)
                    )
                    continue
                split_limit = max(
                    1,
                    min(
                        len(candidate) - 1,
                        len(candidate)
                        * self.config.max_chars
                        // len(cleaned.normalized_text),
                    ),
                )
                subdivisions = split_text_spans(
                    candidate,
                    split_limit,
                    min_chars=min(self.config.min_chars, split_limit),
                )
                if len(subdivisions) < 2:
                    raise ValueError("规范化后的文本无法切入 max_chars")
                pending[0:0] = [
                    (
                        value,
                        candidate_start + relative_start,
                        candidate_start + relative_end,
                    )
                    for value, relative_start, relative_end in subdivisions
                ]
        output: list[Fragment] = []
        for index, (raw_text, start, end, cleaned) in enumerate(fitted):
            if not cleaned.normalized_text:
                continue
            output.append(
                Fragment(
                    element_id=element.element_id,
                    kind=element.kind,
                    section_id=section_id,
                    section_path=section_path,
                    text=cleaned.normalized_text,
                    evidence=self._evidence(
                        element,
                        raw_text,
                        derivation,
                        start=start if keep_offsets else None,
                        end=end if keep_offsets else None,
                        sequence=index,
                    ),
                    content_role=cleaned.content_role,
                    retrieval_enabled=cleaned.retrieval_enabled,
                    whole_element=len(fitted) == 1,
                )
            )
        return output

    def _table_fragments(
        self,
        element: TableElement,
        section_id: str,
        section_path: tuple[str, ...],
    ) -> list[Fragment]:
        """优先使用 HTML 行组，缺失时回退主文本层。"""

        groups = table_text_groups(element.html or "", self.config)
        if groups:
            return [
                self._table_fragment(
                    element,
                    section_id,
                    section_path,
                    text,
                    "table_html_rows",
                    index,
                    whole_element=len(groups) == 1,
                )
                for index, text in enumerate(groups)
            ]
        layer = primary_text_layer(element)
        if not layer or not layer.text.strip():
            return []
        spans = split_text_spans(
            layer.text,
            self.config.max_chars,
            min_chars=self.config.min_chars,
            overlap_sentences=self.config.fragment_overlap_sentences,
        )
        return [
            self._table_fragment(
                element,
                section_id,
                section_path,
                text,
                "table_text_fallback",
                index,
                whole_element=len(spans) == 1,
                start=start,
                end=end,
            )
            for index, (text, start, end) in enumerate(spans)
        ]

    def _table_fragment(
        self,
        element: TableElement,
        section_id: str,
        section_path: tuple[str, ...],
        text: str,
        derivation: Literal["table_html_rows", "table_text_fallback"],
        sequence: int,
        *,
        whole_element: bool,
        start: int | None = None,
        end: int | None = None,
    ) -> Fragment:
        """构造一个表格片段及对应证据。"""

        cleaned = self.cleaner.clean(element, text, section_path)

        return Fragment(
            element_id=element.element_id,
            kind=element.kind,
            section_id=section_id,
            section_path=section_path,
            text=cleaned.normalized_text,
            evidence=self._evidence(
                element,
                text,
                derivation,
                start=start,
                end=end,
                sequence=sequence,
            ),
            content_role=ContentRole.TABLE,
            retrieval_enabled=True,
            whole_element=whole_element,
            table=True,
        )

    def _evidence(
        self,
        element: ElementBase,
        text: str,
        derivation: Literal[
            "primary_text_span",
            "list_items",
            "formula_latex",
            "table_html_rows",
            "table_text_fallback",
        ],
        *,
        start: int | None,
        end: int | None,
        sequence: int,
    ) -> ChunkEvidence:
        """把片段映射为不可变、可回查的证据。"""

        layer = primary_text_layer(element)
        origin = layer.origin if layer else TextOrigin.PARSER_DERIVED
        quality = list(element.quality_issue_ids)
        if origin == TextOrigin.NATIVE_OR_OCR_UNVERIFIED:
            quality.append("chunk_ocr_risk_unverified_origin")
        return ChunkEvidence(
            evidence_id=_evidence_id(
                element.element_id,
                derivation,
                start,
                end,
                sequence,
                text,
            ),
            element_id=element.element_id,
            text_layer_id=layer.text_layer_id if layer else None,
            text_start=start,
            text_end=end,
            text=text,
            text_origin=origin,
            quote_eligible=bool(
                layer and layer.quote_eligible and derivation == "primary_text_span"
            ),
            derivation=derivation,
            locators=element.locators,
            asset_ids=self._assets(element),
            quality_issue_ids=tuple(dict.fromkeys(quality)),
        )

    def _assets(self, element: ElementBase) -> tuple[str, ...]:
        """收集 Element 直接或通过 Locator 引用的资产。"""

        locator_ids = {locator.locator_id for locator in element.locators}
        direct = getattr(element, "asset_id", None)
        values = [
            asset.asset_id
            for asset in self.document.assets
            if locator_ids.intersection(asset.locator_ids)
        ]
        if direct:
            values.insert(0, direct)
        values[0:0] = element.related_asset_ids
        return tuple(dict.fromkeys(values))


def _evidence_id(
    element_id: str,
    derivation: str,
    start: int | None,
    end: int | None,
    sequence: int,
    text: str,
) -> str:
    """根据 Element、跨度和文本内容生成稳定 evidence_id。"""

    identity = (
        element_id,
        derivation,
        start,
        end,
        sequence,
        hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
    return f"evidence_{canonical_sha256(identity)[:24]}"
