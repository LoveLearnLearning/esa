# backend/agent/DocIR/core/geometry.py

"""

这个文件干什么：规范坐标、解析器原始坐标与页面区域。

直白点说就是：统一表示页面上的点、框和区域，并把解析器坐标换算成统一坐标。

规范坐标、解析器原始坐标与页面区域。
"""

from __future__ import annotations

import math
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


class StrictModel(BaseModel):
    """封装 `StrictModel` 的状态与行为。"""
    model_config = ConfigDict(extra="forbid", frozen=True)


class NormalizedBox(StrictModel):
    """封装 `NormalizedBox` 的状态与行为。"""
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def check_order(self) -> "NormalizedBox":
        """检查 `order` 相关数据。"""
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("normalized bbox 必须满足 x1>x0 且 y1>y0")
        return self


class Point(StrictModel):
    """封装 `Point` 的状态与行为。"""
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class SourceGeometry(StrictModel):
    """封装 `SourceGeometry` 的状态与行为。"""
    coordinate_space: str
    bbox: tuple[float, float, float, float]
    page_width: float = Field(gt=0)
    page_height: float = Field(gt=0)

    @field_validator("bbox")
    @classmethod
    def finite_bbox(cls, value: tuple[float, float, float, float]):
        """处理 `finite_bbox` 相关逻辑。"""
        if not all(math.isfinite(item) for item in value):
            raise ValueError("source bbox 必须是有限数")
        if value[2] <= value[0] or value[3] <= value[1]:
            raise ValueError("source bbox 坐标顺序错误")
        return value


class CoordinateTransform(StrictModel):
    """封装 `CoordinateTransform` 的状态与行为。"""
    from_space: str
    to_space: str
    matrix_3x3: tuple[float, float, float, float, float, float, float, float, float]

    @field_validator("matrix_3x3")
    @classmethod
    def invertible(cls, value):
        """处理 `invertible` 相关逻辑。"""
        if not all(math.isfinite(item) for item in value):
            raise ValueError("变换矩阵必须是有限数")
        a, b, c, d, e, f, g, h, i = value
        determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
        if abs(determinant) < 1e-12:
            raise ValueError("变换矩阵不可逆")
        return value


class Locator(StrictModel):
    """可选来源定位；内容合法性不依赖定位或空间坐标。"""

    locator_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    schema_version: Literal["personal-locator-0.1"] | None = None
    container_id: str | None = None
    container_index: int | None = Field(default=None, ge=0)
    label: str | None = None
    page_id: str | None = None
    bbox: NormalizedBox | None = None
    polygon: tuple[Point, ...] | None = None
    source_geometry: SourceGeometry | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    heading_path: tuple[str, ...] | None = None
    start_row: int | None = Field(default=None, ge=1)
    end_row: int | None = Field(default=None, ge=1)
    columns: tuple[str, ...] | None = None
    pointer: str | None = None
    page: int | None = Field(default=None, ge=1)
    asset_id: str | None = None
    ocr_region: str | None = None
    group_id: str | None = None
    section_path: tuple[str, ...] | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("polygon")
    @classmethod
    def polygon_size(cls, value):
        """处理 `polygon_size` 相关逻辑。"""
        if value is not None and len(value) < 3:
            raise ValueError("polygon 至少需要三个点")
        return value

    @model_validator(mode="after")
    def personal_locator_contract(self) -> "Locator":
        """Enforce every format-specific personal Evidence locator."""

        if self.schema_version is None:
            return self
        if self.kind == "text_lines":
            self._ordered(self.start_line, self.end_line, "line")
        elif self.kind == "markdown_section":
            self._ordered(self.start_line, self.end_line, "line")
            if self.heading_path is None:
                raise ValueError("markdown_section requires heading_path")
        elif self.kind == "csv_rows":
            self._ordered(self.start_row, self.end_row, "row")
            if not self.columns:
                raise ValueError("csv_rows requires columns")
        elif self.kind == "json_pointer":
            if self.pointer is None or not _valid_json_pointer(self.pointer):
                raise ValueError("json_pointer requires an RFC 6901 pointer")
        elif self.kind == "pdf_region":
            if self.page is None or self.bbox is None:
                raise ValueError("pdf_region requires page and bbox")
        elif self.kind == "image_region":
            if not self.asset_id or not self.ocr_region or self.bbox is None:
                raise ValueError("image_region requires asset_id, ocr_region and bbox")
        elif self.kind == "mineru_section":
            if not self.group_id or self.section_path is None:
                raise ValueError("mineru_section requires group_id and section_path")
        else:
            raise ValueError("unsupported personal locator kind")
        return self

    @staticmethod
    def _ordered(start: int | None, end: int | None, label: str) -> None:
        if start is None or end is None or end < start:
            raise ValueError(f"{label} range must be present and ordered")


_JSON_POINTER_TOKEN = re.compile(r"(?:[^~/]|~[01])*")


def _valid_json_pointer(value: str) -> bool:
    if value == "":
        return True
    return value.startswith("/") and all(
        _JSON_POINTER_TOKEN.fullmatch(token) is not None
        for token in value[1:].split("/")
    )


def normalize_bbox(raw: list[float] | tuple[float, ...], width: float, height: float) -> NormalizedBox:
    """把左上角原点的页面绝对坐标转换为规范坐标。"""
    if len(raw) != 4 or width <= 0 or height <= 0:
        raise ValueError("无法归一化 bbox")
    x0, y0, x1, y1 = (float(item) for item in raw)
    if not all(math.isfinite(item) for item in (x0, y0, x1, y1)):
        raise ValueError("无法归一化非有限 bbox")
    normalized = (
        max(0.0, min(1.0, x0 / width)),
        max(0.0, min(1.0, y0 / height)),
        max(0.0, min(1.0, x1 / width)),
        max(0.0, min(1.0, y1 / height)),
    )
    return NormalizedBox(
        x0=normalized[0],
        y0=normalized[1],
        x1=normalized[2],
        y1=normalized[3],
    )
