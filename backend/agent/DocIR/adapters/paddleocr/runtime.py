"""Run PP-StructureV3 locally with a pinned GPU-oriented profile."""

from __future__ import annotations

import os
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from .bundle import PaddleOCRBundle
from .models import PaddleOCRAdapterConfig

SUPPORTED_SUFFIXES = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
}


def _require_gpu(device: str) -> None:
    import paddle

    if not paddle.device.is_compiled_with_cuda():
        raise RuntimeError("当前 PaddlePaddle 不是 CUDA 构建")
    count = paddle.device.cuda.device_count()
    index = int(device.split(":", 1)[1]) if ":" in device else 0
    if count <= index:
        raise RuntimeError(f"PaddleOCR 请求 {device}，当前只能访问 {count} 张 GPU")
    paddle.set_device(f"gpu:{index}")


def _source_page_count(source: Path) -> int:
    if source.suffix.lower() != ".pdf":
        return 1
    import pypdfium2

    document = pypdfium2.PdfDocument(source)
    try:
        return len(document)
    finally:
        document.close()


def _page_png(result: Any) -> bytes:
    preprocessed = result["doc_preprocessor_res"]["output_img"]
    image = Image.fromarray(preprocessed[:, :, ::-1])
    stream = BytesIO()
    image.save(stream, format="PNG", optimize=False)
    return stream.getvalue()


def _plain_json(result: Any) -> dict[str, Any]:
    value = result.json
    if isinstance(value, dict) and isinstance(value.get("res"), dict):
        value = value["res"]
    if not isinstance(value, dict):
        raise TypeError("PP-StructureV3 Result.json 不是对象")
    return value


def _configure_model_cache(config: PaddleOCRAdapterConfig) -> None:
    cache = config.model_cache_dir.expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(cache)
    os.environ["HF_HOME"] = str(cache / "huggingface")
    os.environ["PADDLE_PDX_MODEL_SOURCE"] = config.model_source
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["HF_HUB_DISABLE_XET"] = "1"


def _pipeline_kwargs(config: PaddleOCRAdapterConfig) -> dict[str, Any]:
    return {
        "device": config.device,
        "engine": config.engine,
        "use_doc_orientation_classify": config.use_doc_orientation_classify,
        "use_doc_unwarping": config.use_doc_unwarping,
        "use_textline_orientation": config.use_textline_orientation,
        "use_seal_recognition": config.use_seal_recognition,
        "use_table_recognition": config.use_table_recognition,
        "use_formula_recognition": config.use_formula_recognition,
        "use_chart_recognition": config.use_chart_recognition,
        "use_region_detection": config.use_region_detection,
        "text_rec_score_thresh": config.text_rec_score_thresh,
        "layout_detection_model_name": config.layout_detection_model_name,
        "region_detection_model_name": config.region_detection_model_name,
        "text_detection_model_name": config.text_detection_model_name,
        "text_recognition_model_name": config.text_recognition_model_name,
        "table_classification_model_name": config.table_classification_model_name,
        "wired_table_structure_recognition_model_name": (
            config.wired_table_structure_recognition_model_name
        ),
        "wireless_table_structure_recognition_model_name": (
            config.wireless_table_structure_recognition_model_name
        ),
        "wired_table_cells_detection_model_name": (
            config.wired_table_cells_detection_model_name
        ),
        "wireless_table_cells_detection_model_name": (
            config.wireless_table_cells_detection_model_name
        ),
        "formula_recognition_model_name": config.formula_recognition_model_name,
    }


def run_paddleocr(
    source: Path,
    config: PaddleOCRAdapterConfig | None = None,
) -> PaddleOCRBundle:
    """Parse a local PDF/image into an auditable in-memory raw bundle."""

    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    selected = config or PaddleOCRAdapterConfig()
    if source.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"PP-StructureV3 不支持的本地格式: {source.suffix}")
    if source.stat().st_size > selected.max_file_size:
        raise ValueError("输入文件超过 PaddleOCR Adapter max_file_size")
    page_count = _source_page_count(source)
    if page_count > selected.max_num_pages:
        raise ValueError("输入页数超过 PaddleOCR Adapter max_num_pages")

    _configure_model_cache(selected)
    _require_gpu(selected.device)
    from paddleocr import PPStructureV3

    pipeline = PPStructureV3(**_pipeline_kwargs(selected))
    pages: list[dict[str, Any]] = []
    images: list[bytes] = []
    for result in pipeline.predict(str(source)):
        pages.append(_plain_json(result))
        images.append(_page_png(result))
        if len(pages) > selected.max_num_pages:
            raise ValueError("PP-StructureV3 返回页数超过 max_num_pages")
    if len(pages) != page_count:
        raise ValueError(
            f"PP-StructureV3 页数不一致: source={page_count}, parsed={len(pages)}"
        )
    return PaddleOCRBundle(
        pages=tuple(pages),
        page_images=tuple(images),
        status="success",
        version={
            "paddleocr": version("paddleocr"),
            "paddlex": version("paddlex"),
            "paddlepaddle_gpu": version("paddlepaddle-gpu"),
            "pipeline": "PP-StructureV3",
        },
        config=selected.model_dump(mode="json"),
    )
