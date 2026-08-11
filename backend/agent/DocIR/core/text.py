# backend/agent/DocIR/core/text.py

"""

这个文件干什么：文字层模型，明确文字来源与逐字引用资格。

直白点说就是：记录文字内容从哪里来、包含哪些行内片段，以及这段文字能不能安全地直接引用。

文字层模型，明确文字来源与逐字引用资格。
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .enums import TextOrigin
from .geometry import StrictModel


class InlineSpan(StrictModel):
    kind: Literal["text", "inline_formula"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str

    @model_validator(mode="after")
    def offsets(self):
        if self.end <= self.start:
            raise ValueError("inline span end 必须大于 start")
        return self


class TextLayer(StrictModel):
    text_layer_id: str = Field(min_length=1)
    origin: TextOrigin
    text: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    quote_eligible: bool = False
    spans: tuple[InlineSpan, ...] = ()

    @model_validator(mode="after")
    def quotation_and_spans(self):
        if self.origin in {
            TextOrigin.PARSER_DERIVED,
            TextOrigin.VLM_DERIVED,
            TextOrigin.UNKNOWN,
            TextOrigin.NATIVE_OR_OCR_UNVERIFIED,
        } and self.quote_eligible:
            raise ValueError("parser_derived/unknown/unverified 文字不可标记为可逐字引用")
        for span in self.spans:
            if span.end > len(self.text):
                raise ValueError("inline span 超出文字层范围")
        return self


class TextContent(StrictModel):
    primary_layer_id: str
    layers: tuple[TextLayer, ...]

    @model_validator(mode="after")
    def layer_refs(self):
        ids = [layer.text_layer_id for layer in self.layers]
        if len(ids) != len(set(ids)):
            raise ValueError("text_layer_id 不能重复")
        if self.primary_layer_id not in ids:
            raise ValueError("primary_layer_id 必须引用当前 TextContent")
        return self
