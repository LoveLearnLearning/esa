# backend/agent/DocIR/adapters/paddleocr/tests/test_runtime.py

"""验证 `runtime` 相关行为与回归场景。"""

from pathlib import Path
from unittest.mock import MagicMock

from .. import runtime
from ..models import PaddleOCRAdapterConfig


def test_pipeline_receives_string_path(tmp_path: Path, monkeypatch) -> None:
    """验证 `pipeline_receives_string_path` 场景。"""
    source = tmp_path / "source.png"
    source.write_bytes(b"not-used-by-the-mocked-pipeline")
    result = MagicMock()
    result.json = {
        "res": {
            "width": 1,
            "height": 1,
            "page_index": None,
            "page_count": None,
            "parsing_res_list": [],
        }
    }
    result.__getitem__.side_effect = lambda key: {
        "doc_preprocessor_res": {"output_img": _pixel()}
    }[key]
    pipeline = MagicMock()
    pipeline.predict.return_value = [result]
    constructor = MagicMock(return_value=pipeline)

    monkeypatch.setattr(runtime, "_require_gpu", lambda _device: None)
    monkeypatch.setattr(runtime, "_configure_model_cache", lambda _config: None)
    monkeypatch.setitem(
        __import__("sys").modules, "paddleocr", MagicMock(PPStructureV3=constructor)
    )
    bundle = runtime.run_paddleocr(source, PaddleOCRAdapterConfig())
    pipeline.predict.assert_called_once_with(str(source.resolve()))
    assert len(bundle.pages) == 1


def _pixel():
    """处理 `_pixel` 相关逻辑。"""
    import numpy

    return numpy.zeros((1, 1, 3), dtype=numpy.uint8)
