# backend/agent/DocIR/adapters/mineru/alignment.py

"""
这个文件干什么：MinerU middle.json 与 content_list_v2.json 的逐页对齐。

直白点说就是：把 MinerU 两份顺序可能不一样的页面块按坐标和类型一一配对，配不上就明确报错。

MinerU middle.json 与 content_list_v2.json 的逐页对齐。

MinerU 3.4.x 会把页眉、页码放在 ``discarded_blocks`` 中，同时在 V2
列表中保留它们，且两份产物的顺序不一定相同。因此不能使用数组下标
直接 zip，而应使用坐标和类型进行一对一匹配。
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .models import RawMiddleBlock, RawMiddlePage

TYPE_ALIASES: dict[str, frozenset[str]] = {
    "text": frozenset({"paragraph"}),
    "interline_equation": frozenset({"equation_interline"}),
    "code": frozenset({"code", "algorithm"}),
    "header": frozenset({"page_header"}),
}


class AlignmentError(ValueError):
    """middle 与 V2 不能在严格约束下一对一对齐。"""


@dataclass(frozen=True)
class AlignedBlock:
    """封装 `AlignedBlock` 的状态与行为。"""
    middle: RawMiddleBlock
    v2: dict[str, Any] | None
    discarded: bool
    bbox_delta: float | None
    v2_index: int | None


def extract_text(value: Any) -> str:
    """递归提取 MinerU span 文字，不把 HTML/LaTeX 原样当作普通文字。"""
    pieces: list[str] = []

    def visit(item: Any) -> None:
        """处理 `visit` 相关逻辑。"""
        if isinstance(item, dict):
            if item.get("type") in {"text", "inline_text"} and isinstance(item.get("content"), str):
                pieces.append(item["content"])
            for key, child in item.items():
                if key != "content" or not isinstance(child, str):
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return "".join(pieces).strip()


def types_compatible(middle_type: str, v2_type: str | None) -> bool:
    """处理 `types_compatible` 相关逻辑。

    Args:
        middle_type: str => `middle_type` 参数。
        v2_type: str | None => `v2_type` 参数。

    Returns:
        bool => 处理结果。
    """
    if v2_type is None:
        return False
    return middle_type == v2_type or v2_type in TYPE_ALIASES.get(middle_type, frozenset())


def _middle_bbox_1000(
    block: RawMiddleBlock,
    width: float | None,
    height: float | None,
) -> tuple[float, float, float, float] | None:
    """处理 `_middle_bbox_1000` 相关逻辑。"""
    if block.bbox is None and width is None and height is None:
        return None
    if (
        block.bbox is None
        or len(block.bbox) != 4
        or width is None
        or height is None
        or width <= 0
        or height <= 0
    ):
        raise AlignmentError("middle bbox/page_size 不完整")
    x0, y0, x1, y1 = map(float, block.bbox)
    return x0 / width * 1000, y0 / height * 1000, x1 / width * 1000, y1 / height * 1000


def _v2_bbox(item: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """处理 `_v2_bbox` 相关逻辑。"""
    bbox = item.get("bbox")
    if bbox is None:
        return None
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise AlignmentError("content_list_v2 block 缺少四元 bbox")
    return tuple(map(float, bbox))  # type: ignore[return-value]


def _bbox_delta(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    """处理 `_bbox_delta` 相关逻辑。"""
    return max(abs(a - b) for a, b in zip(left, right))


def _text_distance(middle: RawMiddleBlock, v2: dict[str, Any]) -> float:
    """处理 `_text_distance` 相关逻辑。"""
    left = extract_text(middle.model_dump(mode="python"))
    right = extract_text(v2)
    if not left and not right:
        return 0.0
    return 1.0 - SequenceMatcher(None, left, right, autojunk=False).ratio()


def align_page(
    page: RawMiddlePage,
    v2_items: list[Any],
    *,
    strict: bool = False,
    max_bbox_delta: float = 5.0,
) -> list[AlignedBlock]:
    """返回按 V2 阅读顺序排列的对齐块。

    严格模式要求组内基数相等且类型兼容。两侧都提供 geometry 时，
    还要求坐标最大误差不超过 ``max_bbox_delta``（V2 的 0..1000 坐标系）；
    两侧都没有 geometry 时按类型、文本和顺序对齐。
    """
    if page.page_size is None:
        width = height = None
    elif len(page.page_size) == 2:
        width, height = map(float, page.page_size)
    else:
        raise AlignmentError("middle page_size 必须是 width/height 二元组")
    middle_items = [(block, False) for block in page.para_blocks]
    middle_items.extend((block, True) for block in page.discarded_blocks)
    typed_v2 = [item if isinstance(item, dict) else {} for item in v2_items]

    if strict and len(middle_items) != len(typed_v2):
        raise AlignmentError(
            f"page {page.page_idx}: middle+discarded={len(middle_items)}, v2={len(typed_v2)}"
        )

    candidates: list[tuple[int, float, float, int, int]] = []
    actual_deltas: dict[tuple[int, int], float | None] = {}
    for middle_index, (block, _discarded) in enumerate(middle_items):
        middle_bbox = _middle_bbox_1000(block, width, height)
        for v2_index, item in enumerate(typed_v2):
            compatible = types_compatible(block.type, item.get("type"))
            try:
                v2_bbox = _v2_bbox(item)
                if (middle_bbox is None) != (v2_bbox is None):
                    raise AlignmentError("middle 与 V2 geometry presence 不一致")
                delta = (
                    _bbox_delta(middle_bbox, v2_bbox)
                    if middle_bbox is not None and v2_bbox is not None
                    else None
                )
            except AlignmentError:
                if strict:
                    raise
                delta = None
            actual_deltas[(middle_index, v2_index)] = delta
            candidates.append(
                (
                    0 if compatible else 1,
                    delta if delta is not None else 0.0,
                    _text_distance(block, item),
                    middle_index,
                    v2_index,
                )
            )

    matched_middle: set[int] = set()
    matched_v2: set[int] = set()
    pairs: dict[int, tuple[int, float | None]] = {}
    for incompatible, delta, text_delta, middle_index, v2_index in sorted(candidates):
        if middle_index in matched_middle or v2_index in matched_v2:
            continue
        if strict and (incompatible or delta > max_bbox_delta):
            continue
        matched_middle.add(middle_index)
        matched_v2.add(v2_index)
        pairs[v2_index] = (
            middle_index,
            actual_deltas[(middle_index, v2_index)],
        )

    if strict and (len(matched_middle) != len(middle_items) or len(matched_v2) != len(typed_v2)):
        raise AlignmentError(f"page {page.page_idx}: 存在未对齐块或 bbox 超出 {max_bbox_delta}")

    aligned: list[AlignedBlock] = []
    for v2_index in sorted(pairs):
        middle_index, delta = pairs[v2_index]
        block, discarded = middle_items[middle_index]
        item = typed_v2[v2_index]
        if strict and not types_compatible(block.type, item.get("type")):
            raise AlignmentError(
                f"page {page.page_idx}: middle type={block.type}, v2 type={item.get('type')}"
            )
        aligned.append(AlignedBlock(block, item, discarded, delta, v2_index))

    # 宽松模式仍保留无法对齐的 middle 块，避免静默丢数据。
    for middle_index, (block, discarded) in enumerate(middle_items):
        if middle_index not in matched_middle:
            aligned.append(AlignedBlock(block, None, discarded, None, None))
    return aligned
