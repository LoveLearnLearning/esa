# backend/agent/rag/chunk/builder.py

"""

这个文件干什么：把 DocIR V0.2 确定性转换为章节感知 ChunkDocument。

直白点说就是：按章节和长度规则把一份 DocIR 文档切成适合检索的小块，同时保留来源证据。

把 DocIR V0.2 确定性转换为章节感知 ChunkDocument。
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
            "chunk-document-0.1",
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
                resolve(section.parent_section_id)
                if section.parent_section_id
                else ()
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
        drafts: list[Draft] = []
        dispositions: list[ElementDisposition] = []
        normal: list[Fragment] = []
        active_section: str | None = None

        for element in document.elements:
            section_id = element.section_id or root_section_id
            if active_section is not None and active_section != section_id:
                self._flush_normal(normal, drafts)
            active_section = section_id
            section_path = section_paths.get(section_id, ())

            disposition = self._structural_disposition(element)
            if disposition is not None:
                dispositions.append(disposition)
                continue

            if isinstance(element, TableElement):
                self._flush_normal(normal, drafts)
                fragments = factory.build(element, section_id, section_path)
                drafts.extend(Draft(section_id, section_path, [item]) for item in fragments)
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
                normal.extend(fragments)
                action, reason = "chunked", "retrievable_text"
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

    @staticmethod
    def _structural_disposition(
        element: ElementBase,
    ) -> ElementDisposition | None:
        """识别只贡献章节结构或必须排除的 Element。"""

        if isinstance(element, HeadingElement):
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
        """按目标长度聚合普通片段，并只重叠一个完整 Element。"""

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
                current = self._overlap(current[-1], fragment)
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
        return drafts

    def _overlap(self, previous: Fragment, current: Fragment) -> list[Fragment]:
        """在不超过硬上限时保留前一个完整 Element。"""

        if not self.config.overlap_elements or not previous.whole_element:
            return [current]
        candidate = f"{previous.text}\n\n{current.text}"
        return [previous, current] if len(candidate) <= self.config.max_chars else [current]

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
            item.evidence.evidence_id
            for draft in drafts
            for item in draft.fragments
        )
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
    ) -> Chunk:
        """把一个 Draft 转换为正式 Chunk 契约。"""

        body = draft.body
        heading = " > ".join((document.source.filename, *draft.section_path))
        element_ids = tuple(
            dict.fromkeys(item.element_id for item in draft.fragments)
        )
        kinds = Counter(item.kind for item in draft.fragments)
        overlap_groups = tuple(
            sorted(
                {
                    f"overlap_{canonical_sha256(item.evidence.evidence_id)[:24]}"
                    for item in draft.fragments
                    if evidence_counts[item.evidence.evidence_id] > 1
                }
            )
        )
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
            dense_text=f"{heading}\n\n{body}",
            bm25_body=body,
            bm25_heading=heading,
            body_char_count=len(body),
            previous_chunk_id=previous_chunk_id,
            next_chunk_id=next_chunk_id,
            overlap_group_ids=overlap_groups,
            evidence=tuple(item.evidence for item in draft.fragments),
        )


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
