# backend/agent/DocIR/tests/adapters/mineru/test_alignment.py

"""

这个文件干什么：验证 MinerU 两类原始产物的页面块对齐规则和失败边界。

直白点说就是：用正常和异常样本检查页面块能否正确配对，并确保数量或坐标不合理时会报错。
"""

import pytest

from backend.agent.DocIR.adapters.mineru.alignment import (
    AlignmentError,
    align_page,
    types_compatible,
)
from backend.agent.DocIR.adapters.mineru.models import RawMiddleBlock, RawMiddlePage


def block(kind: str, bbox: list[float], index: int) -> RawMiddleBlock:
    return RawMiddleBlock(type=kind, bbox=bbox, index=index)


def test_bbox_alignment_handles_discarded_header_reordered_in_v2():
    page = RawMiddlePage(
        page_idx=0,
        page_size=[1000, 1000],
        para_blocks=[block("title", [10, 100, 300, 150], 1), block("text", [10, 200, 500, 260], 2)],
        discarded_blocks=[block("header", [10, 10, 500, 40], 0)],
    )
    v2 = [
        {"type": "title", "bbox": [10, 100, 300, 150], "content": {}},
        {"type": "paragraph", "bbox": [10, 200, 500, 260], "content": {}},
        {"type": "page_header", "bbox": [10, 10, 500, 40], "content": {}},
    ]
    aligned = align_page(page, v2, strict=True)
    assert [item.middle.type for item in aligned] == ["title", "text", "header"]
    assert [item.discarded for item in aligned] == [False, False, True]
    assert all(item.bbox_delta == 0 for item in aligned)


@pytest.mark.parametrize(
    ("middle_type", "v2_type"),
    [
        ("text", "paragraph"),
        ("interline_equation", "equation_interline"),
        ("code", "code"),
        ("code", "algorithm"),
        ("header", "page_header"),
        ("table", "table"),
    ],
)
def test_observed_type_aliases_are_compatible(middle_type: str, v2_type: str):
    assert types_compatible(middle_type, v2_type)


def test_strict_alignment_rejects_cardinality_mismatch():
    page = RawMiddlePage(
        page_idx=3,
        page_size=[1000, 1000],
        para_blocks=[block("text", [10, 10, 100, 100], 0)],
    )
    with pytest.raises(AlignmentError, match=r"middle\+discarded=1, v2=0"):
        align_page(page, [], strict=True)


def test_strict_alignment_rejects_bbox_beyond_threshold():
    page = RawMiddlePage(
        page_idx=0,
        page_size=[1000, 1000],
        para_blocks=[block("text", [10, 10, 100, 100], 0)],
    )
    v2 = [{"type": "paragraph", "bbox": [50, 50, 140, 140], "content": {}}]
    with pytest.raises(AlignmentError, match="bbox"):
        align_page(page, v2, strict=True, max_bbox_delta=5)
