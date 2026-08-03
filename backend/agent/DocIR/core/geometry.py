# backend/agent/DocIR/core/geometry.py

"""

这个文件干什么：规范坐标、解析器原始坐标与页面区域。

直白点说就是：统一表示页面上的点、框和区域，并把解析器坐标换算成统一坐标。

规范坐标、解析器原始坐标与页面区域。
"""

import math

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NormalizedBox(StrictModel):
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def check_order(self) -> "NormalizedBox":
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("normalized bbox 必须满足 x1>x0 且 y1>y0")
        return self


class Point(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class SourceGeometry(StrictModel):
    coordinate_space: str
    bbox: tuple[float, float, float, float]
    page_width: float = Field(gt=0)
    page_height: float = Field(gt=0)

    @field_validator("bbox")
    @classmethod
    def finite_bbox(cls, value: tuple[float, float, float, float]):
        if not all(math.isfinite(item) for item in value):
            raise ValueError("source bbox 必须是有限数")
        if value[2] <= value[0] or value[3] <= value[1]:
            raise ValueError("source bbox 坐标顺序错误")
        return value


class CoordinateTransform(StrictModel):
    from_space: str
    to_space: str
    matrix_3x3: tuple[float, float, float, float, float, float, float, float, float]

    @field_validator("matrix_3x3")
    @classmethod
    def invertible(cls, value):
        if not all(math.isfinite(item) for item in value):
            raise ValueError("变换矩阵必须是有限数")
        a, b, c, d, e, f, g, h, i = value
        determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
        if abs(determinant) < 1e-12:
            raise ValueError("变换矩阵不可逆")
        return value


class Region(StrictModel):
    region_id: str = Field(min_length=1)
    page_id: str = Field(min_length=1)
    bbox: NormalizedBox
    polygon: tuple[Point, ...] | None = None
    source_geometry: SourceGeometry | None = None

    @field_validator("polygon")
    @classmethod
    def polygon_size(cls, value):
        if value is not None and len(value) < 3:
            raise ValueError("polygon 至少需要三个点")
        return value


def normalize_bbox(raw: list[float] | tuple[float, ...], width: float, height: float) -> NormalizedBox:
    """把左上角原点的页面绝对坐标转换为规范坐标。"""
    if len(raw) != 4 or width <= 0 or height <= 0:
        raise ValueError("无法归一化 bbox")
    x0, y0, x1, y1 = (float(item) for item in raw)
    return NormalizedBox(x0=x0 / width, y0=y0 / height, x1=x1 / width, y1=y1 / height)
