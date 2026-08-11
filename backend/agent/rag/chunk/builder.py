# backend/agent/rag/chunk/builder.py

"""

这个文件干什么：把 DocIR 确定性转换为章节感知 ChunkDocument。

直白点说就是：按章节和长度规则把一份 DocIR 文档切成适合检索的小块，同时保留来源证据。

把 DocIR 确定性转换为章节感知 ChunkDocument。
"""

from __future__ import annotations

from collections import Counter

from backend.agent.DocIR.core.document import Document
from backend.agent.DocIR.core.elements import (
    ElementBase,
    FigureElement,
    HeadingElement,
    TableElement,
)
from backend.agent.DocIR.core.enums import ElementRole

from .cleaning import RetrievalCleaner
from .fragments import (
    Draft,
    ElementFragmentFactory,
    Fragment,
    primary_text_layer,
)
from .models import (
    Chunk,
    ChunkConfig,
    ChunkDocument,
    ChunkEvidence,
    ElementDisposition,
    canonical_sha256,
)

_EXCLUDED_ROLES = {
    ElementRole.HEADER,
    ElementRole.FOOTER,
    ElementRole.PAGE_NUMBER,
    ElementRole.DISCARDED,
}


def _stable(prefix: str, *parts: object) -> str:
    """生成带可读前缀的稳定短 ID。"""

    return f"{prefix}_{canonical_sha256(parts)[:24]}"


class ChunkBuilder:
    """编排章节路径、片段分组和最终 Chunk 物化。"""

    def __init__(self, config: ChunkConfig | None = None) -> None:
        self.config = config or ChunkConfig()

    def build(self, document: Document, *, docir_sha256: str) -> ChunkDocument:
        """把一个已验证 DocIR 文档转换为完整 ChunkDocument。"""

        self._validate_input(document)
        section_paths = self._section_paths(document)
        root_section_id = self._root_section_id(document)
        drafts, dispositions = self._collect_drafts(
            document,
            section_paths,
            root_section_id,
        )
        chunk_revision_id = _stable(
            "chunkrev",
            document.parse_revision.parse_revision_id,
            self.config.sha256,
            "chunk-document-0.2",
        )
        chunks = self._materialize_chunks(
            document,
            drafts,
            chunk_revision_id,
        )
        return ChunkDocument(
            document_id=document.document_id,
            source_version_id=document.source.source_version_id,
            parse_revision_id=document.parse_revision.parse_revision_id,
            filename=document.source.filename,
            docir_sha256=docir_sha256,
            chunk_revision_id=chunk_revision_id,
            chunk_config=self.config,
            chunk_config_sha256=self.config.sha256,
            chunks=tuple(chunks),
            element_dispositions=tuple(dispositions),
        )

    def _validate_input(self, document: Document) -> None:
        """校验会改变 Chunk 构建行为的输入前提。"""

        if self.config.reject_unknown_elements and any(
            element.kind == "unknown" for element in document.elements
        ):
            raise ValueError("ChunkConfig 拒绝 UnknownElement")

    @staticmethod
    def _root_section_id(document: Document) -> str:
        """返回唯一逻辑根章节；缺失时给出明确错误。"""

        root = next(
            (
                section.section_id
                for section in document.sections
                if section.parent_section_id is None
            ),
            None,
        )
        if root is None:
            raise ValueError("DocIR 缺少根 Section")
        return root

    @staticmethod
    def _section_paths(document: Document) -> dict[str, tuple[str, ...]]:
        """根据章节父子关系和标题 Element 构造完整章节路径。"""

        sections = {section.section_id: section for section in document.sections}
        elements = {element.element_id: element for element in document.elements}
        cache: dict[str, tuple[str, ...]] = {}

        def resolve(section_id: str) -> tuple[str, ...]:
            if section_id in cache:
                return cache[section_id]
            section = sections[section_id]
            parent = (
                resolve(section.parent_section_id) if section.parent_section_id else ()
            )
            title = ""
            if section.title_element_id:
                layer = primary_text_layer(elements[section.title_element_id])
                title = layer.text.strip() if layer else ""
            cache[section_id] = parent + ((title,) if title else ())
            return cache[section_id]

        for section_id in sections:
            resolve(section_id)
        return cache

    def _collect_drafts(
        self,
        document: Document,
        section_paths: dict[str, tuple[str, ...]],
        root_section_id: str,
    ) -> tuple[list[Draft], list[ElementDisposition]]:
        """按文档顺序分类 Element，并生成章节内 Chunk 草稿。"""

        factory = ElementFragmentFactory(document, self.config)
        section_title_ids = {
            section.title_element_id
            for section in document.sections
            if section.title_element_id is not None
        }
        drafts: list[Draft] = []
        dispositions: list[ElementDisposition] = []
        normal: list[Fragment] = []
        active_section: str | None = None

        for element in document.elements:
            section_id = element.section_id or root_section_id
            disposition = self._structural_disposition(element, section_title_ids)
            if disposition is not None and disposition.action == "excluded":
                # 页眉、页脚、页码等不应制造正文 Chunk 边界。
                dispositions.append(disposition)
                continue
            if active_section is not None and active_section != section_id:
                self._flush_normal(normal, drafts)
            active_section = section_id
            section_path = section_paths.get(section_id, ())

            if disposition is not None:
                dispositions.append(disposition)
                continue

            label_disposition = self._label_disposition(element)
            if label_disposition is not None:
                dispositions.append(label_disposition)
                continue

            if isinstance(element, TableElement):
                self._flush_normal(normal, drafts)
                fragments = factory.build(element, section_id, section_path)
                drafts.extend(
                    Draft(section_id, section_path, [item]) for item in fragments
                )
                dispositions.append(
                    ElementDisposition(
                        element_id=element.element_id,
                        action="chunked" if fragments else "excluded",
                        reason="table_rows" if fragments else "empty_table",
                    )
                )
                continue

            fragments = factory.build(element, section_id, section_path)
            if fragments:
                if normal and normal[-1].content_role != fragments[0].content_role:
                    self._flush_normal(normal, drafts)
                normal.extend(fragments)
                action = "chunked"
                reason = f"content_role:{fragments[0].content_role.value}"
            else:
                action = "excluded"
                reason = (
                    "empty_figure_no_vlm"
                    if isinstance(element, FigureElement)
                    else "empty_retrievable_text"
                )
            dispositions.append(
                ElementDisposition(
                    element_id=element.element_id,
                    action=action,
                    reason=reason,
                )
            )

        self._flush_normal(normal, drafts)
        return drafts, dispositions

    def _label_disposition(
        self,
        element: ElementBase,
    ) -> ElementDisposition | None:
        """过滤高置信独立图标签和导航标签，不修改 DocIR。"""

        layer = primary_text_layer(element)
        if layer is None:
            return None
        reason = RetrievalCleaner.standalone_exclusion_reason(
            element,
            layer.text,
            filter_standalone_figure_labels=(
                self.config.filter_standalone_figure_labels
            ),
            filter_navigation_labels=self.config.filter_navigation_labels,
        )
        if reason is None:
            return None
        return ElementDisposition(
            element_id=element.element_id,
            action="excluded",
            reason=reason,
        )

    @staticmethod
    def _structural_disposition(
        element: ElementBase,
        section_title_ids: set[str],
    ) -> ElementDisposition | None:
        """识别只贡献章节结构或必须排除的 Element。"""

        if (
            isinstance(element, HeadingElement)
            and element.element_id in section_title_ids
        ):
            return ElementDisposition(
                element_id=element.element_id,
                action="section_structure",
                reason="heading_in_section_path",
            )
        if element.role in _EXCLUDED_ROLES:
            return ElementDisposition(
                element_id=element.element_id,
                action="excluded",
                reason=f"excluded_role:{element.role.value}",
            )
        return None

    def _flush_normal(
        self,
        fragments: list[Fragment],
        drafts: list[Draft],
    ) -> None:
        """把累积的普通片段分组后清空缓冲区。"""

        if fragments:
            drafts.extend(self._normal_drafts(fragments))
            fragments.clear()

    def _normal_drafts(self, fragments: list[Fragment]) -> list[Draft]:
        """按目标长度聚合、合并过短草稿，再重叠一个完整 Element。"""

        drafts: list[Draft] = []
        current: list[Fragment] = []
        for fragment in fragments:
            candidate = "\n\n".join(item.text for item in [*current, fragment])
            if current and len(candidate) > self.config.target_chars:
                drafts.append(
                    Draft(
                        current[0].section_id,
                        current[0].section_path,
                        list(current),
                    )
                )
                current = [fragment]
            else:
                current.append(fragment)
            if len("\n\n".join(item.text for item in current)) > self.config.max_chars:
                raise ValueError("普通 Chunk 超过 max_chars")
        if current:
            drafts.append(
                Draft(
                    current[0].section_id,
                    current[0].section_path,
                    list(current),
                )
            )
        drafts = self._merge_short_drafts(drafts)
        drafts = self._rebalance_short_drafts(drafts)
        return self._add_element_overlap(drafts)

    def _merge_short_drafts(self, drafts: list[Draft]) -> list[Draft]:
        """同章节、同角色内优先向前合并短块，否则尝试向后合并。"""

        minimum = min(self.config.min_chars, self.config.target_chars)
        if minimum <= 0 or len(drafts) < 2:
            return drafts
        output = list(drafts)
        index = 0
        while index < len(output):
            current = output[index]
            if len(current.body) >= minimum or not self._mergeable(current):
                index += 1
                continue
            if index > 0 and self._can_merge(output[index - 1], current):
                output[index - 1].fragments.extend(current.fragments)
                output.pop(index)
                continue
            if index + 1 < len(output) and self._can_merge(current, output[index + 1]):
                current.fragments.extend(output[index + 1].fragments)
                output.pop(index + 1)
                continue
            index += 1
        return output

    @staticmethod
    def _mergeable(draft: Draft) -> bool:
        """表格由独立路径处理；公式、代码、图保持特殊块边界。"""

        return not any(
            item.table or item.kind in {"formula", "code", "figure"}
            for item in draft.fragments
        )

    def _can_merge(self, left: Draft, right: Draft) -> bool:
        if (
            left.section_id != right.section_id
            or left.content_role != right.content_role
            or not self._mergeable(left)
            or not self._mergeable(right)
        ):
            return False
        return len(f"{left.body}\n\n{right.body}") <= self.config.max_chars

    def _rebalance_short_drafts(self, drafts: list[Draft]) -> list[Draft]:
        """从前块尾部移动完整 Fragment，治理无法整块合并的短尾。"""

        minimum = min(self.config.min_chars, self.config.target_chars)
        if minimum <= 0 or len(drafts) < 2:
            return drafts
        output = list(drafts)
        for index in range(1, len(output)):
            left = output[index - 1]
            right = output[index]
            if len(right.body) >= minimum or not self._same_merge_domain(left, right):
                continue
            candidates: list[tuple[int, int, int]] = []
            for cut in range(1, len(left.fragments)):
                left_body = "\n\n".join(item.text for item in left.fragments[:cut])
                right_body = "\n\n".join(
                    item.text for item in [*left.fragments[cut:], *right.fragments]
                )
                if (
                    minimum <= len(left_body) <= self.config.max_chars
                    and minimum <= len(right_body) <= self.config.max_chars
                ):
                    candidates.append(
                        (abs(len(left_body) - len(right_body)), -cut, cut)
                    )
            if not candidates:
                continue
            cut = min(candidates)[2]
            moved = left.fragments[cut:]
            output[index - 1] = Draft(
                left.section_id,
                left.section_path,
                left.fragments[:cut],
            )
            output[index] = Draft(
                right.section_id,
                right.section_path,
                [*moved, *right.fragments],
            )
        return output

    def _same_merge_domain(self, left: Draft, right: Draft) -> bool:
        """判断两个草稿是否允许共享正文边界。"""

        return (
            left.section_id == right.section_id
            and left.content_role == right.content_role
            and self._mergeable(left)
            and self._mergeable(right)
        )

    def _add_element_overlap(self, drafts: list[Draft]) -> list[Draft]:
        """在短块合并完成后，为相邻草稿添加至多一个完整 Element。"""

        if not self.config.overlap_elements:
            return drafts
        output: list[Draft] = []
        previous: Draft | None = None
        for draft in drafts:
            fragments = list(draft.fragments)
            if previous is not None:
                overlap = previous.fragments[-1]
                if (
                    overlap.whole_element
                    and overlap.content_role == draft.content_role
                    and len(f"{overlap.text}\n\n{draft.body}") <= self.config.max_chars
                ):
                    fragments.insert(0, overlap)
            current = Draft(draft.section_id, draft.section_path, fragments)
            output.append(current)
            previous = draft
        return output

    def _materialize_chunks(
        self,
        document: Document,
        drafts: list[Draft],
        chunk_revision_id: str,
    ) -> list[Chunk]:
        """为草稿生成稳定 ID、相邻关系、重叠组和最终检索字段。"""

        chunk_ids = [
            _stable(
                "chunk",
                chunk_revision_id,
                draft.section_id,
                tuple(item.evidence.evidence_id for item in draft.fragments),
            )
            for draft in drafts
        ]
        previous_ids, next_ids = _section_links(drafts, chunk_ids)
        evidence_counts = Counter(
            item.evidence.evidence_id for draft in drafts for item in draft.fragments
        )
        evidence_overlap_groups = _evidence_overlap_groups(drafts)
        return [
            self._materialize_chunk(
                document,
                draft,
                index,
                chunk_id,
                chunk_revision_id,
                previous_ids[index],
                next_ids[index],
                evidence_counts,
                evidence_overlap_groups,
            )
            for index, (draft, chunk_id) in enumerate(zip(drafts, chunk_ids))
        ]

    @staticmethod
    def _materialize_chunk(
        document: Document,
        draft: Draft,
        document_order: int,
        chunk_id: str,
        chunk_revision_id: str,
        previous_chunk_id: str | None,
        next_chunk_id: str | None,
        evidence_counts: Counter[str],
        evidence_overlap_groups: dict[str, set[str]],
    ) -> Chunk:
        """把一个 Draft 转换为正式 Chunk 契约。"""

        if any(
            item.section_id != draft.section_id
            or item.section_path != draft.section_path
            for item in draft.fragments
        ):
            raise ValueError("一个 Chunk 不能包含跨 Section 的 Fragment")
        body = draft.body
        heading = " > ".join((document.source.filename, *draft.section_path))
        element_ids = tuple(dict.fromkeys(item.element_id for item in draft.fragments))
        kinds = Counter(item.kind for item in draft.fragments)
        overlap_group_set: set[str] = set()
        for item in draft.fragments:
            evidence_id = item.evidence.evidence_id
            overlap_group_set.update(evidence_overlap_groups.get(evidence_id, set()))
            if evidence_counts[evidence_id] > 1:
                overlap_group_set.add(
                    f"overlap_{canonical_sha256(evidence_id)[:24]}"
                )
        overlap_groups = tuple(sorted(overlap_group_set))
        return Chunk(
            chunk_id=chunk_id,
            chunk_revision_id=chunk_revision_id,
            document_order=document_order,
            document_id=document.document_id,
            source_version_id=document.source.source_version_id,
            parse_revision_id=document.parse_revision.parse_revision_id,
            section_id=draft.section_id,
            section_path=draft.section_path,
            element_ids=element_ids,
            kind_counts=dict(sorted(kinds.items())),
            content_role=draft.content_role,
            retrieval_enabled=draft.retrieval_enabled,
            dense_text=f"{heading}\n\n{body}",
            bm25_body=body,
            bm25_heading=heading,
            body_char_count=len(body),
            previous_chunk_id=previous_chunk_id,
            next_chunk_id=next_chunk_id,
            overlap_group_ids=overlap_groups,
            evidence=tuple(item.evidence for item in draft.fragments),
        )


def _evidence_overlap_groups(drafts: list[Draft]) -> dict[str, set[str]]:
    """为同一原文层中相交但不相同的跨度生成稳定 overlap group。"""

    by_layer: dict[tuple[str, str | None], dict[str, ChunkEvidence]] = {}
    for draft in drafts:
        for fragment in draft.fragments:
            evidence = fragment.evidence
            if evidence.text_start is None or evidence.text_end is None:
                continue
            by_layer.setdefault(
                (evidence.element_id, evidence.text_layer_id), {}
            )[evidence.evidence_id] = evidence

    groups: dict[str, set[str]] = {}
    for evidence_by_id in by_layer.values():
        evidence_items = sorted(
            evidence_by_id.values(),
            key=lambda item: (item.text_start, item.text_end, item.evidence_id),
        )
        for index, left in enumerate(evidence_items):
            for right in evidence_items[index + 1 :]:
                if right.text_start >= left.text_end:
                    break
                overlap_start = max(left.text_start, right.text_start)
                overlap_end = min(left.text_end, right.text_end)
                if overlap_start >= overlap_end:
                    continue
                group_id = (
                    "overlap_"
                    + canonical_sha256(
                        (
                            left.element_id,
                            left.text_layer_id,
                            overlap_start,
                            overlap_end,
                        )
                    )[:24]
                )
                groups.setdefault(left.evidence_id, set()).add(group_id)
                groups.setdefault(right.evidence_id, set()).add(group_id)
    return groups


def _section_links(
    drafts: list[Draft],
    chunk_ids: list[str],
) -> tuple[list[str | None], list[str | None]]:
    """一次前向和一次反向扫描生成同章节相邻 Chunk ID。"""

    previous: list[str | None] = []
    last_by_section: dict[str, str] = {}
    for draft, chunk_id in zip(drafts, chunk_ids):
        previous.append(last_by_section.get(draft.section_id))
        last_by_section[draft.section_id] = chunk_id

    next_ids: list[str | None] = [None] * len(drafts)
    next_by_section: dict[str, str] = {}
    for index in range(len(drafts) - 1, -1, -1):
        section_id = drafts[index].section_id
        next_ids[index] = next_by_section.get(section_id)
        next_by_section[section_id] = chunk_ids[index]
    return previous, next_ids
