# backend/agent/rag/retrieval/context.py

"""

这个文件干什么：把章节上下文选择和结构化证据映射从主检索服务中独立出来。

直白点说就是：为命中的 Chunk 补上合适的章节上下文，并把内部证据整理成调用方能使用的结构。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import re

from ..chunk import Chunk
from .contracts import ContextLevel, Evidence


@dataclass
class ContextBuilder:
    """在单个章节边界内，为命中 Chunk 选择受控上下文。"""

    chunks: Sequence[Chunk]
    section_window: int
    token_counter: Callable[[str], int] | None = None
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

    def plan(
        self,
        hits: Sequence[Chunk],
        level: ContextLevel,
        max_tokens: int,
    ) -> Mapping[str, tuple[Chunk, ...]]:
        """先装载全部 primary，再按命中顺序装邻居并执行全局去重。"""

        selected: dict[str, list[Chunk]] = {hit.chunk_id: [] for hit in hits}
        used: set[str] = set()
        token_count = 0

        def add(owner: str, chunk: Chunk) -> bool:
            """添加 `add` 相关数据。

            Args:
                owner: str => `owner` 参数。
                chunk: Chunk => `chunk` 参数。

            Returns:
                bool => 处理结果。
            """
            nonlocal token_count
            if chunk.chunk_id in used:
                return False
            cost = self._token_count(chunk.bm25_body) + (1 if used else 0)
            if token_count + cost > max_tokens:
                return False
            selected[owner].append(chunk)
            used.add(chunk.chunk_id)
            token_count += cost
            return True

        active_hits: list[Chunk] = []
        for hit in hits:
            if add(hit.chunk_id, hit):
                active_hits.append(hit)

        for hit in active_hits:
            for chunk in self.select(hit, level):
                if chunk.chunk_id != hit.chunk_id:
                    add(hit.chunk_id, chunk)
        return {
            hit_id: tuple(sorted(parts, key=lambda chunk: chunk.document_order))
            for hit_id, parts in selected.items()
            if parts
        }

    def _token_count(self, text: str) -> int:
        """优先使用已配置 tokenizer，失败时回退到无模型估算。"""

        if self.token_counter is not None:
            try:
                value = self.token_counter(text)
                if value > 0:
                    return value
            except Exception:
                pass
        return estimate_tokens(text)


_TOKEN = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9_]+|[^\s]")
_SAFE_BREAK = re.compile(r"\n{2,}|[。！？!?；;]")
_TRUNCATION_MARKER = "…"


def estimate_tokens(text: str) -> int:
    """无模型依赖的保守 token 估算；CJK、词和标点分别计数。"""

    return len(_TOKEN.findall(text))


def truncate_text_to_token_budget(text: str, max_tokens: int) -> str:
    """按估算 token 预算做确定性摘录，并尽量停在自然边界。"""

    if max_tokens < 0:
        raise ValueError("max_tokens cannot be negative")

    value = text.strip()
    if not value or max_tokens == 0:
        return ""
    if estimate_tokens(value) <= max_tokens:
        return value

    marker_tokens = estimate_tokens(_TRUNCATION_MARKER)
    content_budget = max_tokens - marker_tokens
    if content_budget <= 0:
        return _TRUNCATION_MARKER if marker_tokens <= max_tokens else ""

    tokens = list(_TOKEN.finditer(value))
    cutoff = tokens[content_budget - 1].end()
    prefix = value[:cutoff].rstrip()

    # 不为了句末回退过多内容；后 40% 中存在自然边界时才采用。
    minimum_break = int(len(prefix) * 0.6)
    safe_ends = [
        match.end()
        for match in _SAFE_BREAK.finditer(prefix)
        if match.end() >= minimum_break
    ]
    if safe_ends:
        prefix = prefix[: safe_ends[-1]].rstrip()
    return f"{prefix}{_TRUNCATION_MARKER}"


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
                    locators=tuple(
                        locator.model_dump(mode="json") for locator in item.locators
                    ),
                    asset_ids=item.asset_ids,
                )
            )
        return tuple(output)
