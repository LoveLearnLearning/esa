# backend/agent/rag/chunk/models.py

"""

这个文件干什么：独立 Chunk 模块的稳定数据契约。

直白点说就是：规定切分配置、Chunk、证据和集合清单必须有哪些字段，以及怎样计算稳定哈希。

独立 Chunk 模块的稳定数据契约。
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.agent.DocIR.core.enums import TextOrigin
from backend.agent.DocIR.core.geometry import Locator

SHA256_LENGTH = 64


def canonical_sha256(value: object) -> str:
    """对 JSON 可序列化值计算稳定 SHA-256。"""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class StrictModel(BaseModel):
    """封装 `StrictModel` 的状态与行为。"""
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContentRole(str, Enum):
    """RAG 侧内容角色；不改变 DocIR 对原文事实的表达。"""

    BODY = "body"
    REFERENCE = "reference"
    METADATA = "metadata"
    AUTHOR_INFO = "author_info"
    AFFILIATION = "affiliation"
    CITATION_INFO = "citation_info"
    APPENDIX = "appendix"
    FIGURE_CAPTION = "figure_caption"
    TABLE = "table"


DEFAULT_RETRIEVAL_ROLES = frozenset(
    {
        ContentRole.BODY,
        ContentRole.APPENDIX,
        ContentRole.FIGURE_CAPTION,
        ContentRole.TABLE,
    }
)


class ChunkConfig(StrictModel):
    """保存 `chunk config` 配置。"""
    schema_version: Literal[
        "chunk-config-0.1",
        "chunk-config-0.2",
        "chunk-config-0.3",
    ] = "chunk-config-0.3"
    target_chars: int = Field(default=800, gt=0)
    max_chars: int = Field(default=1200, gt=0)
    min_chars: int = Field(default=120, ge=0)
    overlap_elements: int = Field(default=1, ge=0, le=1)
    fragment_overlap_sentences: int = Field(default=1, ge=0, le=1)
    retrieval_cleaning_version: Literal[
        "retrieval-cleaning-0.4",
        "retrieval-cleaning-0.5",
    ] = (
        "retrieval-cleaning-0.5"
    )
    repeat_table_header: bool = True
    reject_unknown_elements: bool = True
    filter_standalone_figure_labels: bool = True
    filter_navigation_labels: bool = True

    @model_validator(mode="after")
    def ordered_limits(self) -> ChunkConfig:
        """处理 `ordered_limits` 相关逻辑。"""
        if self.target_chars > self.max_chars:
            raise ValueError("target_chars 不能大于 max_chars")
        return self

    @property
    def sha256(self) -> str:
        """处理 `sha256` 相关逻辑。"""
        payload = self.model_dump(mode="json")
        if self.schema_version == "chunk-config-0.1":
            payload = {
                key: payload[key]
                for key in (
                    "schema_version",
                    "target_chars",
                    "max_chars",
                    "overlap_elements",
                    "repeat_table_header",
                    "reject_unknown_elements",
                )
            }
        elif self.schema_version == "chunk-config-0.2":
            payload = {
                key: payload[key]
                for key in (
                    "schema_version",
                    "target_chars",
                    "max_chars",
                    "min_chars",
                    "overlap_elements",
                    "fragment_overlap_sentences",
                    "retrieval_cleaning_version",
                    "repeat_table_header",
                    "reject_unknown_elements",
                )
            }
        return canonical_sha256(payload)


class ChunkEvidence(StrictModel):
    """封装 `ChunkEvidence` 的状态与行为。"""
    evidence_id: str = Field(min_length=1)
    element_id: str = Field(min_length=1)
    text_layer_id: str | None = None
    text_start: int | None = Field(default=None, ge=0)
    text_end: int | None = Field(default=None, gt=0)
    text: str = Field(min_length=1)
    text_origin: TextOrigin
    quote_eligible: bool = False
    derivation: Literal[
        "primary_text_span",
        "list_items",
        "formula_latex",
        "table_html_rows",
        "table_text_fallback",
    ]
    locators: tuple[Locator, ...] = ()
    asset_ids: tuple[str, ...] = ()
    quality_issue_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def valid_span(self) -> ChunkEvidence:
        """处理 `valid_span` 相关逻辑。"""
        if (self.text_start is None) != (self.text_end is None):
            raise ValueError("text_start/text_end 必须同时存在或同时为空")
        if self.text_start is not None and self.text_end is not None:
            if self.text_end <= self.text_start:
                raise ValueError("evidence 文本跨度顺序错误")
            if (
                self.derivation == "primary_text_span"
                and self.text_end - self.text_start != len(self.text)
            ):
                raise ValueError("primary_text_span 长度与 evidence 文本不一致")
        return self

    @model_validator(mode="after")
    def valid_location(self) -> ChunkEvidence:
        """处理 `valid_location` 相关逻辑。"""
        locator_ids = [locator.locator_id for locator in self.locators]
        if len(locator_ids) != len(set(locator_ids)):
            raise ValueError("evidence locator_id 不能重复")
        return self

    @model_validator(mode="after")
    def valid_quote_eligibility(self) -> ChunkEvidence:
        """处理 `valid_quote_eligibility` 相关逻辑。"""
        if (
            self.text_origin
            in {
                TextOrigin.PARSER_DERIVED,
                TextOrigin.VLM_DERIVED,
                TextOrigin.UNKNOWN,
                TextOrigin.NATIVE_OR_OCR_UNVERIFIED,
            }
            and self.quote_eligible
        ):
            raise ValueError("派生、未知或未验证文字不能提升引用资格")
        return self


class Chunk(StrictModel):
    """封装 `Chunk` 的状态与行为。"""
    chunk_id: str = Field(min_length=1)
    chunk_revision_id: str = Field(min_length=1)
    document_order: int = Field(ge=0)
    document_id: str = Field(min_length=1)
    source_version_id: str = Field(min_length=1)
    parse_revision_id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    section_path: tuple[str, ...] = ()
    element_ids: tuple[str, ...] = Field(min_length=1)
    kind_counts: dict[str, int]
    content_role: ContentRole = ContentRole.BODY
    retrieval_enabled: bool = True
    dense_text: str = Field(min_length=1)
    bm25_body: str = Field(min_length=1)
    bm25_heading: str = Field(min_length=1)
    body_char_count: int = Field(gt=0)
    previous_chunk_id: str | None = None
    next_chunk_id: str | None = None
    overlap_group_ids: tuple[str, ...] = ()
    evidence: tuple[ChunkEvidence, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def internal_consistency(self) -> Chunk:
        """处理 `internal_consistency` 相关逻辑。"""
        if self.body_char_count != len(self.bm25_body):
            raise ValueError("body_char_count 与 bm25_body 长度不一致")
        evidence_elements = tuple(
            dict.fromkeys(item.element_id for item in self.evidence)
        )
        if evidence_elements != self.element_ids:
            raise ValueError("element_ids 必须等于 evidence 中首次出现的 element 顺序")
        if any(value <= 0 for value in self.kind_counts.values()):
            raise ValueError("kind_counts 必须为正整数")
        return self


class ElementDisposition(StrictModel):
    """封装 `ElementDisposition` 的状态与行为。"""
    element_id: str = Field(min_length=1)
    action: Literal["chunked", "section_structure", "excluded"]
    reason: str = Field(min_length=1)


class ChunkDocument(StrictModel):
    """封装 `ChunkDocument` 的状态与行为。"""
    schema_name: Literal["chunk_document"] = "chunk_document"
    schema_version: Literal["0.1"] = "0.1"
    document_id: str = Field(min_length=1)
    source_version_id: str = Field(min_length=1)
    parse_revision_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    docir_sha256: str
    chunk_revision_id: str = Field(min_length=1)
    chunk_config: ChunkConfig
    chunk_config_sha256: str
    chunks: tuple[Chunk, ...]
    element_dispositions: tuple[ElementDisposition, ...]

    @field_validator("docir_sha256", "chunk_config_sha256")
    @classmethod
    def sha_format(cls, value: str) -> str:
        """处理 `sha_format` 相关逻辑。"""
        if len(value) != SHA256_LENGTH or any(
            char not in "0123456789abcdef" for char in value
        ):
            raise ValueError("SHA-256 必须为 64 位小写十六进制")
        return value

    @model_validator(mode="after")
    def valid_config_and_order(self) -> ChunkDocument:
        """处理 `valid_config_and_order` 相关逻辑。"""
        if self.chunk_config_sha256 != self.chunk_config.sha256:
            raise ValueError("chunk_config_sha256 与配置不一致")
        ids = [chunk.chunk_id for chunk in self.chunks]
        if len(ids) != len(set(ids)):
            raise ValueError("chunk_id 不能重复")
        if [chunk.document_order for chunk in self.chunks] != list(
            range(len(self.chunks))
        ):
            raise ValueError("Chunk document_order 必须从 0 连续")
        return self

    @model_validator(mode="after")
    def valid_chunk_identity_and_links(self) -> ChunkDocument:
        """处理 `valid_chunk_identity_and_links` 相关逻辑。"""
        by_id = {chunk.chunk_id: chunk for chunk in self.chunks}
        for chunk in self.chunks:
            if chunk.body_char_count > self.chunk_config.max_chars:
                raise ValueError("Chunk 正文超过 max_chars")
            if (
                chunk.document_id != self.document_id
                or chunk.source_version_id != self.source_version_id
                or chunk.parse_revision_id != self.parse_revision_id
                or chunk.chunk_revision_id != self.chunk_revision_id
            ):
                raise ValueError("Chunk 版本身份与 ChunkDocument 不一致")
            for linked in (chunk.previous_chunk_id, chunk.next_chunk_id):
                if linked is not None and linked not in by_id:
                    raise ValueError("Chunk 相邻引用不存在")
                if linked is not None and by_id[linked].section_id != chunk.section_id:
                    raise ValueError("Chunk 相邻引用不能跨 Section")
        return self

    @model_validator(mode="after")
    def valid_element_dispositions(self) -> ChunkDocument:
        """处理 `valid_element_dispositions` 相关逻辑。"""
        dispositions = {item.element_id: item for item in self.element_dispositions}
        if len(dispositions) != len(self.element_dispositions):
            raise ValueError("每个 element 只能有一个处理分类")
        for chunk in self.chunks:
            if any(
                dispositions.get(element_id) is None for element_id in chunk.element_ids
            ):
                raise ValueError("Chunk 引用了未分类 element")
            if any(
                dispositions[element_id].action != "chunked"
                for element_id in chunk.element_ids
            ):
                raise ValueError("进入 Chunk 的 element 必须分类为 chunked")
        referenced = {
            element_id for chunk in self.chunks for element_id in chunk.element_ids
        }
        if any(
            item.action == "chunked" and item.element_id not in referenced
            for item in self.element_dispositions
        ):
            raise ValueError("分类为 chunked 的 element 必须出现在至少一个 Chunk 中")
        return self

    @model_validator(mode="after")
    def valid_overlap_groups(self) -> ChunkDocument:
        """处理 `valid_overlap_groups` 相关逻辑。"""
        evidence_locations: dict[str, list[Chunk]] = {}
        evidence_by_layer: dict[
            tuple[str, str | None], list[tuple[ChunkEvidence, Chunk]]
        ] = {}
        for chunk in self.chunks:
            for item in chunk.evidence:
                evidence_locations.setdefault(item.evidence_id, []).append(chunk)
                if item.text_start is not None and item.text_end is not None:
                    evidence_by_layer.setdefault(
                        (item.element_id, item.text_layer_id), []
                    ).append((item, chunk))
        for evidence_id, owners in evidence_locations.items():
            if len(owners) > 1:
                expected = f"overlap_{canonical_sha256(evidence_id)[:24]}"
                if any(expected not in owner.overlap_group_ids for owner in owners):
                    raise ValueError("重复 evidence 必须用稳定 overlap group 标记")
        if self.chunk_config.schema_version != "chunk-config-0.3":
            return self
        for located in evidence_by_layer.values():
            ordered = sorted(
                located,
                key=lambda pair: (
                    pair[0].text_start,
                    pair[0].text_end,
                    pair[0].evidence_id,
                    pair[1].chunk_id,
                ),
            )
            for index, (left, left_chunk) in enumerate(ordered):
                for right, right_chunk in ordered[index + 1 :]:
                    if right.text_start >= left.text_end:
                        break
                    if left.evidence_id == right.evidence_id:
                        continue
                    overlap_start = max(left.text_start, right.text_start)
                    overlap_end = min(left.text_end, right.text_end)
                    if overlap_start >= overlap_end:
                        continue
                    expected = (
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
                    if (
                        expected not in left_chunk.overlap_group_ids
                        or expected not in right_chunk.overlap_group_ids
                    ):
                        raise ValueError("相交 evidence 必须用稳定 overlap group 标记")
        return self


class ChunkDocumentRef(StrictModel):
    """封装 `ChunkDocumentRef` 的状态与行为。"""
    document_id: str = Field(min_length=1)
    source_version_id: str = Field(min_length=1)
    parse_revision_id: str = Field(min_length=1)
    chunk_revision_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str
    chunk_count: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        """处理 `safe_relative_path` 相关逻辑。"""
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("ChunkDocumentRef.path 必须是安全相对路径")
        return value

    @field_validator("sha256")
    @classmethod
    def sha_format(cls, value: str) -> str:
        """处理 `sha_format` 相关逻辑。"""
        if len(value) != SHA256_LENGTH or any(
            char not in "0123456789abcdef" for char in value
        ):
            raise ValueError("SHA-256 必须为 64 位小写十六进制")
        return value


class ChunkCollection(StrictModel):
    """封装 `ChunkCollection` 的状态与行为。"""
    schema_name: Literal["chunk_collection"] = "chunk_collection"
    schema_version: Literal["0.1"] = "0.1"
    collection_id: str = Field(min_length=1)
    chunk_config: ChunkConfig
    chunk_config_sha256: str
    documents: tuple[ChunkDocumentRef, ...]
    document_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)

    @model_validator(mode="after")
    def totals_and_config(self) -> ChunkCollection:
        """处理 `totals_and_config` 相关逻辑。"""
        if self.chunk_config_sha256 != self.chunk_config.sha256:
            raise ValueError("manifest 配置哈希不一致")
        if self.document_count != len(self.documents):
            raise ValueError("document_count 与 documents 不一致")
        if self.chunk_count != sum(item.chunk_count for item in self.documents):
            raise ValueError("chunk_count 与文档引用不一致")
        ids = [item.document_id for item in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("manifest document_id 不能重复")
        return self
