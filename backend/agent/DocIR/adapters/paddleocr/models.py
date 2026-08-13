"""Configuration for the local PP-StructureV3-to-DocIR adapter."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PaddleOCRAdapterConfig(BaseModel):
    """Auditable local PaddleOCR settings with an explicit GPU requirement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    device: str = "gpu:0"
    engine: str = "paddle"
    model_cache_dir: Path = Path("/tmp/esa-paddleocr-cache")
    model_source: str = "huggingface"
    max_num_pages: int = Field(default=1000, ge=1)
    max_file_size: int = Field(default=100 * 1024 * 1024, ge=1)
    text_rec_score_thresh: float = Field(default=0.0, ge=0, le=1)
    low_confidence_threshold: float = Field(default=0.5, ge=0, le=1)
    use_doc_orientation_classify: bool = False
    use_doc_unwarping: bool = False
    use_textline_orientation: bool = False
    use_seal_recognition: bool = False
    use_table_recognition: bool = True
    use_formula_recognition: bool = True
    use_chart_recognition: bool = False
    use_region_detection: bool = True

    layout_detection_model_name: str = "PP-DocLayout_plus-L"
    region_detection_model_name: str = "PP-DocBlockLayout"
    text_detection_model_name: str = "PP-OCRv5_server_det"
    text_recognition_model_name: str = "PP-OCRv5_server_rec"
    table_classification_model_name: str = "PP-LCNet_x1_0_table_cls"
    wired_table_structure_recognition_model_name: str = "SLANeXt_wired"
    wireless_table_structure_recognition_model_name: str = "SLANet_plus"
    wired_table_cells_detection_model_name: str = "RT-DETR-L_wired_table_cell_det"
    wireless_table_cells_detection_model_name: str = "RT-DETR-L_wireless_table_cell_det"
    formula_recognition_model_name: str = "PP-FormulaNet_plus-L"

    @field_validator("device")
    @classmethod
    def gpu_device(cls, value: str) -> str:
        if not re.fullmatch(r"gpu(?::\d+)?", value):
            raise ValueError("PaddleOCR Adapter 只接受 gpu 或 gpu:<index>")
        return value

    @field_validator("engine")
    @classmethod
    def paddle_engine(cls, value: str) -> str:
        if value != "paddle":
            raise ValueError("PaddleOCR Adapter 只启用本地 PaddlePaddle 引擎")
        return value

    @field_validator("model_source")
    @classmethod
    def supported_model_source(cls, value: str) -> str:
        if value not in {"huggingface", "modelscope", "aistudio", "bos"}:
            raise ValueError("不支持的 PaddleX 模型源")
        return value
