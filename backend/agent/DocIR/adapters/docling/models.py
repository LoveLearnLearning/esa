# backend/agent/DocIR/adapters/docling/models.py

"""Configuration for the Docling-to-DocIR adapter."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DoclingAdapterConfig(BaseModel):
    """Auditable local Docling pipeline settings.

    The default deliberately requires CUDA.  It does not silently fall back to
    CPU, enable remote services, load external plugins, or run VLM enrichment.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    device: str = "cuda"
    num_threads: int = Field(default=4, ge=1)
    document_timeout_seconds: float | None = Field(default=600.0, gt=0)
    max_num_pages: int = Field(default=1000, ge=1)
    max_file_size: int = Field(default=100 * 1024 * 1024, ge=1)
    do_ocr: bool = True
    do_table_structure: bool = True
    generate_page_images: bool = True
    generate_picture_images: bool = True
    images_scale: float = Field(default=1.0, gt=0)

    @field_validator("device")
    @classmethod
    def cuda_device(cls, value: str) -> str:
        """处理 `cuda_device` 相关逻辑。"""
        if not re.fullmatch(r"cuda(?::\d+)?", value):
            raise ValueError("Docling Adapter 只接受 cuda 或 cuda:<index>")
        return value
