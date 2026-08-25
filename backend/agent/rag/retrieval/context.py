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


@dataclass(frozen=True)
class _ExpansionCandidate:
    """A context-only candidate; it never changes the primary result ranking."""

    chunk: Chunk
    source_priority: int
    relevance: float
    distance: int


@dataclass(frozen=True)
class ContextSegment:
    """A source Chunk paired with the exact text admitted to the token budget."""

    chunk: Chunk
    text: str


@dataclass
class ContextBuilder:
    """在单个章节边界内，为命中 Chunk 选择受控上下文。"""

    chunks: Sequence[Chunk]
    section_window: int
    token_counter: Callable[[str], int] | None = None
    _sections: Mapping[tuple[str, str], list[Chunk]] = field(init=False, repr=False)
    _chunks: Mapping[str, Chunk] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """按 section_id 分组，并固定章节内的 Chunk 顺序。"""

        sections: dict[tuple[str, str], list[Chunk]] = {}
        for chunk in self.chunks:
            sections.setdefault((chunk.document_id, chunk.section_id), []).append(chunk)
        for section_chunks in sections.values():
            section_chunks.sort(key=lambda chunk: chunk.document_order)
        self._sections = sections
        self._chunks = {chunk.chunk_id: chunk for chunk in self.chunks}

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
        merged_context_chunk_ids: Mapping[str, Sequence[str]] | None = None,
        query: str = "",
    ) -> Mapping[str, tuple[ContextSegment, ...]]:
        """Keep ranked primaries fixed, then fairly allocate context expansion."""

        if max_tokens <= 0:
            return {}
        active_hits = self._primary_hits_that_can_receive_text(hits, max_tokens)
        selected: dict[str, list[ContextSegment]] = {
            hit.chunk_id: [] for hit in active_hits
        }
        used = {hit.chunk_id for hit in active_hits}
        separator_tokens = max(0, len(active_hits) - 1)
        primary_text_budget = max_tokens - separator_tokens
        primary_demands = {
            hit.chunk_id: self._token_count(hit.bm25_body) for hit in active_hits
        }
        primary_allowances = _fair_token_budgets(
            primary_demands,
            primary_text_budget,
        )
        token_count = separator_tokens
        for hit in active_hits:
            text = self._excerpt_to_budget(
                hit.bm25_body,
                query,
                primary_allowances[hit.chunk_id],
            )
            if not text:
                continue
            selected[hit.chunk_id].append(ContextSegment(hit, text))
            token_count += self._token_count(text)

        # Expansion candidates are deliberately planned after the result ranking and
        # primary inclusion are fixed. They can enrich a hit but cannot reorder it.
        expansion_queues = self._expansion_queues(
            active_hits,
            level,
            merged_context_chunk_ids or {},
            query,
            used,
        )
        remaining = max(0, max_tokens - token_count)
        demands = {
            hit.chunk_id: sum(
                self._token_count(candidate.chunk.bm25_body) + 1
                for candidate in expansion_queues[hit.chunk_id]
            )
            for hit in active_hits
        }
        allowances = _fair_token_budgets(demands, remaining)
        pending: dict[str, list[_ExpansionCandidate]] = {}

        for hit in active_hits:
            owner = hit.chunk_id
            allowance = allowances[owner]
            pending[owner] = []
            for candidate in expansion_queues[owner]:
                cost = self._token_count(candidate.chunk.bm25_body) + 1
                if cost <= allowance and self._add_expansion(
                    selected,
                    used,
                    owner,
                    candidate.chunk,
                ):
                    allowance -= cost
                    token_count += cost
                else:
                    pending[owner].append(candidate)

        # Whole chunks are indivisible here. Redistribute quota that could not be
        # used because an owner's next chunk was too large, one owner per round.
        while token_count < max_tokens:
            progressed = False
            for hit in active_hits:
                owner = hit.chunk_id
                queue = pending[owner]
                fitting_index = next(
                    (
                        index
                        for index, candidate in enumerate(queue)
                        if token_count
                        + self._token_count(candidate.chunk.bm25_body)
                        + 1
                        <= max_tokens
                    ),
                    None,
                )
                if fitting_index is None:
                    continue
                candidate = queue.pop(fitting_index)
                cost = self._token_count(candidate.chunk.bm25_body) + 1
                if self._add_expansion(
                    selected,
                    used,
                    owner,
                    candidate.chunk,
                ):
                    token_count += cost
                    progressed = True
            if not progressed:
                break
        return {
            hit_id: tuple(
                sorted(parts, key=lambda part: part.chunk.document_order)
            )
            for hit_id, parts in selected.items()
            if parts
        }

    def _primary_hits_that_can_receive_text(
        self,
        hits: Sequence[Chunk],
        max_tokens: int,
    ) -> list[Chunk]:
        """Keep the longest ranked prefix for which every hit can receive one token."""

        unique_hits = list({hit.chunk_id: hit for hit in hits}.values())
        count = min(len(unique_hits), (max_tokens + 1) // 2)
        return unique_hits[:count]

    def _excerpt_to_budget(self, text: str, query: str, budget: int) -> str:
        """Find the largest query-aware excerpt accepted by the active counter."""

        if budget <= 0:
            return ""
        if self._token_count(text) <= budget:
            return text
        low = 1
        high = estimate_tokens(text)
        best = ""
        while low <= high:
            middle = (low + high) // 2
            candidate = query_aware_excerpt(text, query, middle)
            if self._token_count(candidate) <= budget:
                best = candidate
                low = middle + 1
            else:
                high = middle - 1
        return best

    @staticmethod
    def _add_expansion(
        selected: dict[str, list[ContextSegment]],
        used: set[str],
        owner: str,
        chunk: Chunk,
    ) -> bool:
        if chunk.chunk_id in used:
            return False
        selected[owner].append(ContextSegment(chunk, chunk.bm25_body))
        used.add(chunk.chunk_id)
        return True

    def _expansion_queues(
        self,
        hits: Sequence[Chunk],
        level: ContextLevel,
        merged_context_chunk_ids: Mapping[str, Sequence[str]],
        query: str,
        used: set[str],
    ) -> Mapping[str, tuple[_ExpansionCandidate, ...]]:
        """Assign each expansion chunk to its best owner without changing hit order."""

        proposals: dict[
            str,
            list[tuple[int, str, _ExpansionCandidate]],
        ] = {}
        for owner_rank, hit in enumerate(hits):
            local: dict[str, _ExpansionCandidate] = {}
            for chunk_id in merged_context_chunk_ids.get(hit.chunk_id, ()):
                chunk = self._chunks.get(chunk_id)
                if chunk is not None and chunk.chunk_id not in used:
                    local[chunk.chunk_id] = self._expansion_candidate(
                        hit,
                        chunk,
                        source_priority=0,
                        query=query,
                    )
            for chunk in self.select(hit, level):
                if chunk.chunk_id == hit.chunk_id or chunk.chunk_id in used:
                    continue
                candidate = self._expansion_candidate(
                    hit,
                    chunk,
                    source_priority=1,
                    query=query,
                )
                current = local.get(chunk.chunk_id)
                if current is None or _expansion_sort_key(candidate) < _expansion_sort_key(
                    current
                ):
                    local[chunk.chunk_id] = candidate
            for candidate in local.values():
                proposals.setdefault(candidate.chunk.chunk_id, []).append(
                    (owner_rank, hit.chunk_id, candidate)
                )

        queues: dict[str, list[_ExpansionCandidate]] = {
            hit.chunk_id: [] for hit in hits
        }
        for choices in proposals.values():
            _rank, owner, candidate = min(
                choices,
                key=lambda choice: (
                    *_expansion_sort_key(choice[2]),
                    choice[0],
                ),
            )
            queues[owner].append(candidate)
        return {
            owner: tuple(sorted(values, key=_expansion_sort_key))
            for owner, values in queues.items()
        }

    @staticmethod
    def _expansion_candidate(
        owner: Chunk,
        chunk: Chunk,
        *,
        source_priority: int,
        query: str,
    ) -> _ExpansionCandidate:
        return _ExpansionCandidate(
            chunk=chunk,
            source_priority=source_priority,
            relevance=query_relevance_score(query, chunk.bm25_body),
            distance=abs(owner.document_order - chunk.document_order),
        )

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


def _expansion_sort_key(
    candidate: _ExpansionCandidate,
) -> tuple[int, float, int, int, str]:
    return (
        candidate.source_priority,
        -candidate.relevance,
        candidate.distance,
        candidate.chunk.document_order,
        candidate.chunk.chunk_id,
    )


def _fair_token_budgets(
    demands: Mapping[str, int],
    total: int,
) -> dict[str, int]:
    """Water-fill token quotas in mapping order and redistribute unused shares."""

    budgets = {owner: 0 for owner in demands}
    active = [owner for owner, demand in demands.items() if demand > 0]
    remaining = max(0, total)
    while active and remaining > 0:
        share, remainder = divmod(remaining, len(active))
        if share == 0:
            for owner in active[:remainder]:
                budgets[owner] += 1
            break
        satisfied = [
            owner
            for owner in active
            if demands[owner] - budgets[owner] <= share
        ]
        if satisfied:
            for owner in satisfied:
                needed = demands[owner] - budgets[owner]
                budgets[owner] += needed
                remaining -= needed
                active.remove(owner)
            continue
        for index, owner in enumerate(active):
            budgets[owner] += share + int(index < remainder)
        break
    return budgets


_TOKEN = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9_]+|[^\s]")
_SAFE_BREAK = re.compile(r"\n{2,}|[。！？!?；;]")
_ASCII_QUERY_TERM = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:/#-]*")
_CJK_QUERY_RUN = re.compile(r"[\u3400-\u9fff]+")
_TRUNCATION_MARKER = "…"


def estimate_tokens(text: str) -> int:
    """无模型依赖的保守 token 估算；CJK、词和标点分别计数。"""

    return len(_TOKEN.findall(text))


def query_relevance_score(query: str, text: str) -> float:
    """Return a deterministic lexical relevance score for local projection work."""

    value = text.casefold()
    score = 0.0
    for term in _query_terms(query):
        occurrences = min(3, value.count(term))
        if occurrences:
            score += occurrences * max(1.0, len(term) / 2)
    return score


def rank_evidence_for_query(
    query: str,
    evidence: Sequence[Evidence],
) -> tuple[Evidence, ...]:
    """Put the most query-relevant Evidence first without losing stable order."""

    values = tuple(evidence)
    scored = [
        query_relevance_score(query, f"{' '.join(item.section_path)}\n{item.evidence_text}")
        for item in values
    ]
    if not scored or max(scored) <= 0:
        return values
    return tuple(
        item
        for _index, item in sorted(
            enumerate(values),
            key=lambda pair: (-scored[pair[0]], pair[0]),
        )
    )


def _query_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    terms.extend(
        match.group(0).casefold()
        for match in _ASCII_QUERY_TERM.finditer(query)
        if len(match.group(0)) >= 2
    )
    for match in _CJK_QUERY_RUN.finditer(query):
        run = match.group(0)
        if len(run) <= 4:
            terms.append(run)
        for size in (3, 2):
            terms.extend(run[index : index + size] for index in range(len(run) - size + 1))
    return tuple(dict.fromkeys(term for term in terms if term))


def query_aware_excerpt(text: str, query: str, max_tokens: int) -> str:
    """Extract a bounded window around the passage most related to the query."""

    if max_tokens < 0:
        raise ValueError("max_tokens cannot be negative")
    value = text.strip()
    tokens = list(_TOKEN.finditer(value))
    if not value or max_tokens == 0:
        return ""
    if len(tokens) <= max_tokens:
        return value
    if max_tokens <= 2:
        return truncate_text_to_token_budget(value, max_tokens)

    terms = _query_terms(query)
    anchors: list[tuple[float, int, int]] = []
    folded = value.casefold()
    for term in terms:
        start = folded.find(term)
        while start >= 0:
            anchors.append((max(1.0, len(term) / 2), start, start + len(term)))
            start = folded.find(term, start + 1)
    if not anchors:
        return truncate_text_to_token_budget(value, max_tokens)

    best = max(
        anchors,
        key=lambda anchor: (
            sum(
                weight
                for weight, start, end in anchors
                if start < anchor[2] + 160 and end > anchor[1] - 160
            ),
            anchor[0],
            -anchor[1],
        ),
    )
    center = (best[1] + best[2]) // 2
    center_index = next(
        (index for index, token in enumerate(tokens) if token.end() >= center),
        len(tokens) - 1,
    )
    start = max(0, center_index - max_tokens // 2)
    end = min(len(tokens), start + max_tokens)
    start = max(0, end - max_tokens)

    while True:
        marker_count = int(start > 0) + int(end < len(tokens))
        if end - start + marker_count <= max_tokens:
            break
        if center_index - start >= end - center_index:
            start += 1
        else:
            end -= 1
    while end - start + int(start > 0) + int(end < len(tokens)) < max_tokens:
        if start > 0:
            start -= 1
        elif end < len(tokens):
            end += 1
        else:
            break

    excerpt = value[tokens[start].start() : tokens[end - 1].end()].strip()
    if start > 0:
        excerpt = f"{_TRUNCATION_MARKER}{excerpt}"
    if end < len(tokens):
        excerpt = f"{excerpt}{_TRUNCATION_MARKER}"
    return excerpt


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
