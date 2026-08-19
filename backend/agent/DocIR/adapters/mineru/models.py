# backend/agent/DocIR/adapters/mineru/models.py

"""

这个文件干什么：MinerU 3.4.x raw 模型；允许未知字段以承受小版本漂移。

直白点说就是：先用数据模型接住 MinerU 原始 JSON，即使小版本多出字段也尽量不要直接崩掉。

MinerU 3.4.x raw 模型；允许未知字段以承受小版本漂移。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawModel(BaseModel):
    """封装 `RawModel` 的状态与行为。"""
    model_config = ConfigDict(extra="allow")

    def field_was_provided(self, name: str) -> bool:
        """区分 raw JSON 中缺字段与显式提供 null/empty 的字段。"""

        return name in self.model_fields_set

    def provided_payload(self) -> dict[str, Any]:
        """保留 alias、extras 和 missing 状态的已建模 payload。"""

        return self.model_dump(mode="json", by_alias=True, exclude_unset=True)


class RawMiddleBlock(RawModel):
    """封装 `RawMiddleBlock` 的状态与行为。"""
    type: str
    bbox: list[float] | None = None
    bbox_fs: list[float] | None = None
    index: int | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    level: int | None = None
    lines: list[dict[str, Any]] | None = None
    is_numbered_style: bool | None = None
    attribute: str | None = None
    ilevel: int | None = None


class RawMiddlePage(RawModel):
    """封装 `RawMiddlePage` 的状态与行为。"""
    page_idx: int
    page_size: list[float] | None = None
    para_blocks: list[RawMiddleBlock] = Field(default_factory=list)
    discarded_blocks: list[RawMiddleBlock] = Field(default_factory=list)
    preproc_blocks: list[dict[str, Any]] | None = None


class RawMiddleDocument(RawModel):
    """封装 `RawMiddleDocument` 的状态与行为。"""
    pdf_info: list[RawMiddlePage]
    backend: str | None = Field(default=None, alias="_backend")
    version_name: str | None = Field(default=None, alias="_version_name")
