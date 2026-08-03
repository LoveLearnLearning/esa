# backend/agent/DocIR/adapters/mineru/models.py

"""

这个文件干什么：MinerU 3.4.x raw 模型；允许未知字段以承受小版本漂移。

直白点说就是：先用数据模型接住 MinerU 原始 JSON，即使小版本多出字段也尽量不要直接崩掉。

MinerU 3.4.x raw 模型；允许未知字段以承受小版本漂移。
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class RawMiddleBlock(RawModel):
    type: str
    bbox: list[float]
    index: int | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    level: int | None = None
    lines: list[dict[str, Any]] = Field(default_factory=list)


class RawMiddlePage(RawModel):
    page_idx: int
    page_size: list[float]
    para_blocks: list[RawMiddleBlock] = Field(default_factory=list)
    discarded_blocks: list[RawMiddleBlock] = Field(default_factory=list)


class RawMiddleDocument(RawModel):
    pdf_info: list[RawMiddlePage]
    backend: str | None = Field(default=None, alias="_backend")
    version_name: str | None = Field(default=None, alias="_version_name")
