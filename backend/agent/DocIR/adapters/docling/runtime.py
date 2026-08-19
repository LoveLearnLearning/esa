# backend/agent/DocIR/adapters/docling/runtime.py

"""Run Docling locally with the adapter's explicit CUDA profile."""

from __future__ import annotations

from pathlib import Path

from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import (
    DocumentConverter,
    ImageFormatOption,
    PdfFormatOption,
)

from .bundle import DoclingBundle
from .models import DoclingAdapterConfig

SUPPORTED_FORMATS = (
    InputFormat.PDF,
    InputFormat.IMAGE,
    InputFormat.DOCX,
    InputFormat.PPTX,
    InputFormat.XLSX,
)


def _require_cuda(device: str) -> None:
    """处理 `_require_cuda` 相关逻辑。"""
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError(
            f"Docling Adapter 配置要求 {device}，但 PyTorch 无法访问 CUDA"
        )
    if ":" in device:
        index = int(device.split(":", 1)[1])
        if index >= torch.cuda.device_count():
            raise RuntimeError(
                f"Docling Adapter 请求 {device}，当前只有 {torch.cuda.device_count()} 张 GPU"
            )


def _pipeline_options(config: DoclingAdapterConfig) -> PdfPipelineOptions:
    """处理 `_pipeline_options` 相关逻辑。"""
    return PdfPipelineOptions(
        accelerator_options=AcceleratorOptions(
            device=config.device,
            num_threads=config.num_threads,
        ),
        document_timeout=config.document_timeout_seconds,
        enable_remote_services=False,
        allow_external_plugins=False,
        do_ocr=config.do_ocr,
        do_table_structure=config.do_table_structure,
        generate_page_images=config.generate_page_images,
        generate_picture_images=config.generate_picture_images,
        images_scale=config.images_scale,
        do_picture_classification=False,
        do_picture_description=False,
        do_chart_extraction=False,
        do_code_enrichment=False,
        do_formula_enrichment=False,
    )


def run_docling(
    source: Path,
    config: DoclingAdapterConfig | None = None,
) -> DoclingBundle:
    """Convert one local source file into an auditable in-memory bundle."""

    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    selected = config or DoclingAdapterConfig()
    _require_cuda(selected.device)
    options = _pipeline_options(selected)
    converter = DocumentConverter(
        allowed_formats=list(SUPPORTED_FORMATS),
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=options),
        },
    )
    result = converter.convert(
        source,
        raises_on_error=False,
        max_num_pages=selected.max_num_pages,
        max_file_size=selected.max_file_size,
    )
    return DoclingBundle(
        document=result.document,
        status=result.status.value,
        version=result.version.model_dump(mode="json"),
        config=selected.model_dump(mode="json"),
        errors=tuple(error.model_dump(mode="json") for error in result.errors),
        timestamp=result.timestamp,
        timings={
            name: timing.model_dump(mode="json")
            for name, timing in result.timings.items()
        },
    )
