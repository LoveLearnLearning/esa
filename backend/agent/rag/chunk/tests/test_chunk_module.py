# backend/agent/rag/chunk/tests/test_chunk_module.py

"""

这个文件干什么：验证从 DocIR 构建 Chunk 的切分、重叠、表格、证据和序列化规则。

直白点说就是：用各种文档样本检查切块不会丢字、越界或丢证据，保存后也必须能原样读回。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.agent.DocIR.core import (
    Asset,
    AssetKind,
    Document,
    ElementRole,
    FigureElement,
    HeadingElement,
    Locator,
    NormalizedBox,
    Page,
    PageRange,
    ParagraphElement,
    ParseRevision,
    Section,
    SourceVersion,
    TableElement,
    TextContent,
    TextLayer,
    TextOrigin,
    ValidationStatus,
    ValidationSummary,
)
from backend.agent.DocIR.io import save_document
from backend.agent.rag.chunk import (
    ChunkBuilder,
    ChunkConfig,
    load_chunk_document,
    save_json,
    split_text_spans,
)
from backend.agent.rag.chunk.cli import build_collection
from backend.agent.rag.chunk.serializer import file_sha256


def _text(element_id: str, value: str) -> TextContent | None:
    if not value:
        return None
    layer_id = f"text_{element_id}"
    return TextContent(
        primary_layer_id=layer_id,
        layers=(
            TextLayer(
                text_layer_id=layer_id,
                origin=TextOrigin.NATIVE_OR_OCR_UNVERIFIED,
                text=value,
                quote_eligible=False,
            ),
        ),
    )


def make_document(specs: list[dict]) -> Document:
    elements = []
    for index, spec in enumerate(specs):
        element_id = f"element_{index}"
        locators = [] if spec.get("no_locator") else [
            Locator(
                locator_id=f"locator_{index}_0",
                kind="page",
                container_id="page_000000",
                container_index=0,
                page_id="page_000000",
                bbox=NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2),
            )
        ]
        if spec.get("multipage"):
            locators.append(
                Locator(
                    locator_id=f"locator_{index}_1",
                    kind="page",
                    container_id="page_000001",
                    container_index=1,
                    page_id="page_000001",
                    bbox=NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2),
                )
            )
        common = {
            "element_id": element_id,
            "document_order": index,
            "role": spec.get("role", ElementRole.BODY),
            "section_id": spec.get("section_id", "section_root"),
            "locators": tuple(locators),
            "text": _text(element_id, spec.get("text", "")),
            "source_type": spec.get("source_type", spec.get("kind", "paragraph")),
        }
        kind = spec.get("kind", "paragraph")
        if kind == "heading":
            element = HeadingElement(**common, level=1)
        elif kind == "table":
            element = TableElement(**common, html=spec.get("html"), asset_id=None)
        elif kind == "figure":
            element = FigureElement(**common, asset_id=None)
        else:
            element = ParagraphElement(**common)
        elements.append(element)
    section_ids = tuple(dict.fromkeys(item.section_id for item in elements))
    sections = []
    for section_id in (
        "section_root",
        *(item for item in section_ids if item != "section_root"),
    ):
        members = tuple(
            item.element_id for item in elements if item.section_id == section_id
        )
        title = next(
            (
                item.element_id
                for item in elements
                if item.kind == "heading" and item.section_id == section_id
            ),
            None,
        )
        sections.append(
            Section(
                section_id=section_id,
                parent_section_id=None
                if section_id == "section_root"
                else "section_root",
                title_element_id=title,
                element_ids=members,
            )
        )
    return Document(
        document_id="doc_test",
        created_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        source=SourceVersion(
            source_version_id="src_test",
            filename="测试文档.pdf",
            media_type="application/pdf",
            byte_size=10,
            sha256="b" * 64,
            original_asset_id="asset_original",
        ),
        parse_revision=ParseRevision(
            parse_revision_id="parse_test",
            parser_name="test",
            parser_version="1",
            page_range=PageRange(start=0, end=1),
            config={},
            config_sha256="a" * 64,
        ),
        source_page_count=2,
        parsed_page_count=2,
        pages=(
            Page(
                page_id="page_000000",
                page_index=0,
                display_page_no=1,
                width=100,
                height=100,
            ),
            Page(
                page_id="page_000001",
                page_index=1,
                display_page_no=2,
                width=100,
                height=100,
            ),
        ),
        sections=tuple(sections),
        elements=tuple(elements),
        assets=(
            Asset(
                asset_id="asset_original",
                kind=AssetKind.ORIGINAL,
                path="assets/source.pdf",
                media_type="application/pdf",
                byte_size=10,
                sha256="b" * 64,
            ),
        ),
        validation=ValidationSummary(status=ValidationStatus.PASSED),
    )


def test_config_is_strict_and_ordered() -> None:
    default = ChunkConfig()
    assert default.schema_version == "chunk-config-0.3"
    assert default.sha256 == ChunkConfig().sha256
    assert default.sha256 != default.model_copy(
        update={"filter_navigation_labels": False}
    ).sha256
    with pytest.raises(ValidationError, match="target_chars"):
        ChunkConfig(target_chars=20, max_chars=10)
    with pytest.raises(ValidationError):
        ChunkConfig.model_validate({"extra": 1})


def test_text_split_prefers_boundaries_and_preserves_offsets() -> None:
    text = "第一句。第二句很长。第三句。"
    pieces = split_text_spans(text, 8)
    assert all(len(value) <= 8 for value, _start, _end in pieces)
    assert all(text[start:end] == value for value, start, end in pieces)
    assert "".join(value for value, _start, _end in pieces) == text


def test_text_split_rebalances_an_avoidable_short_tail() -> None:
    text = "甲" * 25

    pieces = split_text_spans(text, 20, min_chars=8)

    assert [len(value) for value, _start, _end in pieces] == [17, 8]
    assert "".join(value for value, _start, _end in pieces) == text
    assert all(text[start:end] == value for value, start, end in pieces)


def test_heading_roles_and_empty_figure_have_explicit_dispositions() -> None:
    document = make_document(
        [
            {"kind": "heading", "text": "第一章"},
            {"text": "正文内容"},
            {"text": "页眉", "role": ElementRole.HEADER},
            {"kind": "figure", "text": ""},
        ]
    )
    result = ChunkBuilder().build(document, docir_sha256="c" * 64)
    disposition = {
        item.element_id: (item.action, item.reason)
        for item in result.element_dispositions
    }
    assert disposition["element_0"] == ("section_structure", "heading_in_section_path")
    assert disposition["element_2"] == ("excluded", "excluded_role:header")
    assert disposition["element_3"] == ("excluded", "empty_figure_no_vlm")
    assert result.chunks[0].section_path == ("第一章",)
    assert "页眉" not in result.chunks[0].bm25_body


def test_standalone_figure_and_navigation_labels_are_filtered_conservatively() -> None:
    document = make_document(
        [
            {"kind": "figure", "text": "图 4-59"},
            {"kind": "figure", "text": "图P6.48（续）"},
            {"kind": "figure", "text": "Fig. 4-2"},
            {"kind": "figure", "text": "32比特"},
            {"kind": "figure", "text": "图4-3 栈帧"},
            {"text": "原书第8版"},
            {"text": "第7章"},
            {"text": "8"},
            {"text": "树"},
            {"text": "大端法"},
        ]
    )

    result = ChunkBuilder(ChunkConfig(min_chars=0, overlap_elements=0)).build(
        document, docir_sha256="c" * 64
    )
    dispositions = {
        item.element_id: (item.action, item.reason)
        for item in result.element_dispositions
    }

    for element_id in ("element_0", "element_1", "element_2", "element_3"):
        assert dispositions[element_id] == ("excluded", "figure_label_only")
    for element_id in ("element_5", "element_6"):
        assert dispositions[element_id] == ("excluded", "navigation_label_only")
    retained = "\n".join(chunk.bm25_body for chunk in result.chunks)
    assert "图4-3 栈帧" in retained
    assert "\n8\n" in f"\n{retained}\n"
    assert "树" in retained
    assert "大端法" in retained


def test_standalone_label_filters_can_be_disabled() -> None:
    result = ChunkBuilder(
        ChunkConfig(
            min_chars=0,
            overlap_elements=0,
            filter_standalone_figure_labels=False,
            filter_navigation_labels=False,
        )
    ).build(
        make_document(
            [
                {"kind": "figure", "text": "图 4-59"},
                {"text": "原书第8版"},
            ]
        ),
        docir_sha256="c" * 64,
    )

    assert [item.action for item in result.element_dispositions] == [
        "chunked",
        "chunked",
    ]
    assert len(result.chunks) == 2


def test_element_without_locator_still_builds_evidence() -> None:
    document = make_document([{"text": "没有空间定位的正文", "no_locator": True}])

    result = ChunkBuilder().build(document, docir_sha256="c" * 64)

    assert result.chunks
    assert result.chunks[0].evidence[0].locators == ()


def test_normal_chunks_overlap_one_whole_element_and_mark_group() -> None:
    document = make_document(
        [
            {"text": "甲" * 10},
            {"text": "乙" * 10},
            {"text": "丙" * 10},
        ]
    )
    result = ChunkBuilder(
        ChunkConfig(target_chars=15, max_chars=30, min_chars=0)
    ).build(document, docir_sha256="c" * 64)
    assert len(result.chunks) == 3
    assert (
        result.chunks[0].evidence[0].evidence_id
        == result.chunks[1].evidence[0].evidence_id
    )
    assert (
        result.chunks[1].evidence[-1].evidence_id
        == result.chunks[2].evidence[0].evidence_id
    )
    assert all(chunk.overlap_group_ids for chunk in result.chunks)
    assert all(chunk.body_char_count <= 30 for chunk in result.chunks)


def test_overlap_is_skipped_when_it_would_exceed_hard_limit() -> None:
    document = make_document([{"text": "甲" * 25}, {"text": "乙" * 10}])
    result = ChunkBuilder(
        ChunkConfig(target_chars=20, max_chars=30, min_chars=0)
    ).build(document, docir_sha256="c" * 64)
    assert len(result.chunks) == 2
    assert not result.chunks[0].overlap_group_ids
    assert not result.chunks[1].overlap_group_ids


def test_oversized_element_splits_without_losing_text() -> None:
    value = "长句。" * 30
    document = make_document([{"text": value}])
    result = ChunkBuilder(
        ChunkConfig(
            target_chars=20, max_chars=25, min_chars=0, fragment_overlap_sentences=0
        )
    ).build(document, docir_sha256="c" * 64)
    evidence = [item.text for chunk in result.chunks for item in chunk.evidence]
    assert "".join(evidence) == value
    assert all(chunk.body_char_count <= 25 for chunk in result.chunks)


def test_normalization_expansion_still_respects_hard_limit() -> None:
    value = "目录……" * 30
    result = ChunkBuilder(
        ChunkConfig(
            target_chars=20,
            max_chars=25,
            min_chars=0,
            overlap_elements=0,
            fragment_overlap_sentences=0,
        )
    ).build(make_document([{"text": value}]), docir_sha256="c" * 64)

    evidence = [item.text for chunk in result.chunks for item in chunk.evidence]
    assert "".join(evidence) == value
    assert all(chunk.body_char_count <= 25 for chunk in result.chunks)


def test_table_uses_repeated_header_and_consecutive_row_groups() -> None:
    html = (
        "<table><thead><tr><th>姓名</th><th>分数</th></tr></thead><tbody>"
        + "".join(f"<tr><td>学生{i}</td><td>{i}</td></tr>" for i in range(8))
        + "</tbody></table>"
    )
    document = make_document(
        [{"kind": "table", "text": "表格文字", "html": html, "multipage": True}]
    )
    result = ChunkBuilder(ChunkConfig(target_chars=30, max_chars=45)).build(
        document, docir_sha256="c" * 64
    )
    assert len(result.chunks) > 1
    assert all(chunk.bm25_body.startswith("姓名 | 分数") for chunk in result.chunks)
    assert all(chunk.body_char_count <= 45 for chunk in result.chunks)
    assert all(len(chunk.evidence[0].locators) == 2 for chunk in result.chunks)
    combined = "\n".join(chunk.bm25_body for chunk in result.chunks)
    assert all(combined.count(f"学生{i} | {i}") == 1 for i in range(8))


def test_table_without_html_falls_back_to_primary_text() -> None:
    document = make_document([{"kind": "table", "text": "A B C " * 20, "html": None}])
    result = ChunkBuilder(ChunkConfig(target_chars=20, max_chars=25)).build(
        document, docir_sha256="c" * 64
    )
    assert result.chunks
    assert all(
        item.derivation == "table_text_fallback"
        for chunk in result.chunks
        for item in chunk.evidence
    )
    assert all(chunk.body_char_count <= 25 for chunk in result.chunks)


def test_unverified_text_is_retrievable_but_not_quotable() -> None:
    result = ChunkBuilder().build(
        make_document([{"text": "OCR 风险内容"}]), docir_sha256="c" * 64
    )
    evidence = result.chunks[0].evidence[0]
    assert evidence.text_origin == TextOrigin.NATIVE_OR_OCR_UNVERIFIED
    assert evidence.quote_eligible is False
    assert "chunk_ocr_risk_unverified_origin" in evidence.quality_issue_ids


def test_serialization_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    source = make_document([{"text": "稳定输出"}])
    document = ChunkBuilder().build(source, docir_sha256="c" * 64)
    rebuilt = ChunkBuilder().build(source, docir_sha256="c" * 64)
    assert [chunk.chunk_id for chunk in rebuilt.chunks] == [
        chunk.chunk_id for chunk in document.chunks
    ]
    assert [chunk.evidence for chunk in rebuilt.chunks] == [
        chunk.evidence for chunk in document.chunks
    ]
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    save_json(document, first)
    save_json(document, second)
    assert first.read_bytes() == second.read_bytes()
    assert load_chunk_document(first) == document


def test_build_collection_resume_verifies_existing_document(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    bundle = input_root / "one"
    bundle.mkdir(parents=True)
    save_document(make_document([{"text": "真实语料"}]), bundle / "document.json")
    output_root = tmp_path / "output"
    root, first, _stats = build_collection(
        input_root, output_root, ChunkConfig(), resume=True
    )
    audit = json.loads((root / "short_chunk_audit.json").read_text(encoding="utf-8"))
    assert audit["threshold_exclusive"] == 120
    assert audit["short_chunk_count"] == 1
    assert audit["chunks"][0]["retention_reason"] == "meaningful_short_element"
    document_path = root / first.documents[0].path
    before = file_sha256(document_path)
    root2, second, _stats2 = build_collection(
        input_root, output_root, ChunkConfig(), resume=True
    )
    assert root2 == root and second == first and file_sha256(document_path) == before
    changed = load_chunk_document(document_path).model_copy(
        update={"filename": "被篡改.pdf"}
    )
    save_json(changed, document_path)
    with pytest.raises(ValueError, match="SHA-256"):
        build_collection(input_root, output_root, ChunkConfig(), resume=True)


def test_cleaning_classifies_roles_without_changing_raw_evidence() -> None:
    document = make_document(
        [
            {"text": "TITLE: Retrieval Study"},
            {"text": "AUTHORS: A. Researcher"},
            {"text": "Department of Computing", "source_type": "affiliation"},
            {"text": "Smith et al. (2025)", "source_type": "ref_text"},
            {"text": "<span>Normal   body</span>\u200b text"},
        ]
    )
    result = ChunkBuilder(ChunkConfig(min_chars=0, overlap_elements=0)).build(
        document, docir_sha256="c" * 64
    )
    roles = [chunk.content_role.value for chunk in result.chunks]
    assert roles == ["metadata", "author_info", "affiliation", "reference", "body"]
    assert [chunk.retrieval_enabled for chunk in result.chunks] == [
        False,
        False,
        False,
        False,
        True,
    ]
    body = result.chunks[-1]
    assert body.bm25_body == "Normal body text"
    assert body.evidence[0].text == "<span>Normal   body</span>\u200b text"


def test_normal_body_mentioning_university_is_not_affiliation() -> None:
    result = ChunkBuilder(ChunkConfig(min_chars=0)).build(
        make_document([{"text": "The university deployed the system to learners."}]),
        docir_sha256="c" * 64,
    )
    assert result.chunks[0].content_role.value == "body"
    assert result.chunks[0].retrieval_enabled is True


def test_front_matter_author_and_date_are_suppressed_conservatively() -> None:
    result = ChunkBuilder(ChunkConfig(min_chars=0, overlap_elements=0)).build(
        make_document(
            [
                {"text": "Hicham Mouncif"},
                {"text": "January 14, 2025"},
                {"text": "The university deployed the system to learners."},
            ]
        ),
        docir_sha256="c" * 64,
    )
    assert [chunk.content_role.value for chunk in result.chunks] == [
        "author_info",
        "metadata",
        "body",
    ]


def test_normalization_only_changes_retrieval_copy() -> None:
    raw = "<span>ef-\nfective</span> \\mathrm { s e l e c t i o n }"
    result = ChunkBuilder(ChunkConfig(min_chars=0)).build(
        make_document([{"text": raw}]), docir_sha256="c" * 64
    )
    chunk = result.chunks[0]
    assert chunk.evidence[0].text == raw
    assert chunk.bm25_body == "effective \\mathrm {selection}"


def test_short_chunks_merge_without_exceeding_hard_limit() -> None:
    result = ChunkBuilder(
        ChunkConfig(
            target_chars=25,
            max_chars=50,
            min_chars=20,
            overlap_elements=0,
        )
    ).build(
        make_document([{"text": "甲" * 12}, {"text": "乙" * 12}, {"text": "丙" * 30}]),
        docir_sha256="c" * 64,
    )
    assert len(result.chunks) == 2
    assert result.chunks[0].element_ids == ("element_0", "element_1")
    assert all(chunk.body_char_count <= 50 for chunk in result.chunks)


def test_short_chunks_never_merge_across_sections() -> None:
    result = ChunkBuilder(
        ChunkConfig(target_chars=25, max_chars=50, min_chars=20, overlap_elements=0)
    ).build(
        make_document(
            [
                {"text": "甲" * 10, "section_id": "section_root"},
                {"text": "乙" * 10, "section_id": "section_other"},
            ]
        ),
        docir_sha256="c" * 64,
    )
    assert len(result.chunks) == 2
    assert result.chunks[0].section_id != result.chunks[1].section_id


def test_short_tail_rebalances_by_moving_complete_fragments() -> None:
    result = ChunkBuilder(
        ChunkConfig(
            target_chars=50,
            max_chars=50,
            min_chars=20,
            overlap_elements=0,
        )
    ).build(
        make_document(
            [
                {"text": "甲" * 15},
                {"text": "乙" * 15},
                {"text": "丙" * 13},
                {"text": "丁" * 10},
            ]
        ),
        docir_sha256="c" * 64,
    )

    assert [chunk.body_char_count for chunk in result.chunks] == [32, 25]
    assert result.chunks[0].element_ids == ("element_0", "element_1")
    assert result.chunks[1].element_ids == ("element_2", "element_3")


def test_short_chunks_do_not_rebalance_across_roles_or_special_elements() -> None:
    role_result = ChunkBuilder(
        ChunkConfig(target_chars=50, max_chars=50, min_chars=20, overlap_elements=0)
    ).build(
        make_document(
            [
                {"text": "正文" * 15},
                {"text": "引用", "source_type": "reference"},
            ]
        ),
        docir_sha256="c" * 64,
    )
    special_result = ChunkBuilder(
        ChunkConfig(target_chars=50, max_chars=50, min_chars=20, overlap_elements=0)
    ).build(
        make_document(
            [
                {"text": "正文" * 15},
                {"kind": "figure", "text": "图4-3 栈帧"},
            ]
        ),
        docir_sha256="c" * 64,
    )

    assert len(role_result.chunks) == 2
    assert role_result.chunks[0].content_role != role_result.chunks[1].content_role
    assert len(special_result.chunks) == 2
    assert special_result.chunks[1].kind_counts == {"figure": 1}


def test_meaningful_short_term_dense_text_uses_complete_section_path() -> None:
    result = ChunkBuilder().build(
        make_document(
            [
                {"kind": "heading", "text": "体系结构"},
                {
                    "kind": "heading",
                    "text": "数据表示",
                    "section_id": "section_other",
                },
                {"text": "大端法", "section_id": "section_other"},
            ]
        ),
        docir_sha256="c" * 64,
    )

    assert result.chunks[0].section_path == ("体系结构", "数据表示")
    assert result.chunks[0].dense_text.startswith(
        "测试文档.pdf > 体系结构 > 数据表示\n\n大端法"
    )


def test_fragment_overlap_is_one_sentence_and_preserves_raw_offsets() -> None:
    value = "第一句很长。第二句也很长。第三句继续很长。第四句结束。"
    result = ChunkBuilder(
        ChunkConfig(
            target_chars=18,
            max_chars=20,
            min_chars=0,
            overlap_elements=0,
            fragment_overlap_sentences=1,
        )
    ).build(make_document([{"text": value}]), docir_sha256="c" * 64)
    evidence = [item for chunk in result.chunks for item in chunk.evidence]
    assert len(evidence) >= 2
    assert any(
        current.text_start < previous.text_end
        for previous, current in zip(evidence, evidence[1:])
    )
    assert any(
        set(previous.overlap_group_ids).intersection(current.overlap_group_ids)
        for previous, current in zip(result.chunks, result.chunks[1:])
    )
    assert all(value[item.text_start : item.text_end] == item.text for item in evidence)
    assert all(chunk.body_char_count <= 20 for chunk in result.chunks)
