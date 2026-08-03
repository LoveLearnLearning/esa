# backend/agent/rag/retrieval/context.py

"""

这个文件干什么：把章节上下文选择和结构化证据映射从主检索服务中独立出来。

直白点说就是：为命中的 Chunk 补上合适的章节上下文，并把内部证据整理成调用方能使用的结构。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ..chunk import Chunk
from .contracts import ContextLevel, Evidence


@dataclass
class ContextBuilder:
    """在单个章节边界内，为命中 Chunk 选择受控上下文。"""

    chunks: Sequence[Chunk]
    section_window: int
    _sections: Mapping[tuple[str, str], list[Chunk]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """按 section_id 分组，并固定章节内的 Chunk 顺序。"""

        sections: dict[tuple[str, str], list[Chunk]] = {}
        for chunk in self.chunks:
            sections.setdefault((chunk.document_id, chunk.section_id), []).append(chunk)
        for section_chunks in sections.values():
            section_chunks.sort(key=lambda chunk: chunk.document_order)
        self._sections = sections

    def select(
        self,
        hit: Chunk,
        level: ContextLevel,
    ) -> list[Chunk]:
        """根据证据档、章节档或完整读取档返回同一章节内的 Chunk。"""

        section = self._sections[(hit.document_id, hit.section_id)]
        position = next(
            index
            for index, chunk in enumerate(section)
            if chunk.chunk_id == hit.chunk_id
        )
        if level == ContextLevel.EVIDENCE:
            return [hit]
        if level == ContextLevel.FULL_READ:
            return section

        start = max(0, position - self.section_window)
        end = min(len(section), position + self.section_window + 1)
        return section[start:end]


class EvidenceAssembler:
    """只使用权威引用字段组装结构化证据，不接触检索拼接文本。"""

    @staticmethod
    def build(chunk: Chunk, document_name: str) -> tuple[Evidence, ...]:
        """把一个 Chunk 的全部可引用区域转换为不可变 Evidence 元组。"""

        output = []
        for item in chunk.evidence:
            output.append(
                Evidence(
                    evidence_id=item.evidence_id,
                    chunk_id=chunk.chunk_id,
                    element_id=item.element_id,
                    text_layer_id=item.text_layer_id,
                    text_start=item.text_start,
                    text_end=item.text_end,
                    evidence_text=item.text,
                    text_origin=item.text_origin.value,
                    quote_eligible=item.quote_eligible,
                    derivation=item.derivation,
                    quality_issue_ids=item.quality_issue_ids,
                    document_id=chunk.document_id,
                    source_version_id=chunk.source_version_id,
                    parse_revision_id=chunk.parse_revision_id,
                    document_name=document_name,
                    section_path=tuple(chunk.section_path),
                    region_ids=item.region_ids,
                    page_ids=item.page_ids,
                    page_indexes=item.page_indexes,
                    asset_ids=item.asset_ids,
                )
            )
        return tuple(output)
