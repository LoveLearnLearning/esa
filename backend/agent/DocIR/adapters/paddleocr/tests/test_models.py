# backend/agent/DocIR/adapters/paddleocr/tests/test_models.py

"""验证 `models` 相关行为与回归场景。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from ..models import PaddleOCRAdapterConfig


def test_config_requires_local_paddle_gpu_profile() -> None:
    """验证 `config_requires_local_paddle_gpu_profile` 场景。"""
    config = PaddleOCRAdapterConfig()
    assert config.device == "gpu:0"
    assert config.engine == "paddle"
    assert config.model_cache_dir == Path("/tmp/esa-paddleocr-cache")
    with pytest.raises(ValidationError):
        PaddleOCRAdapterConfig(device="cpu")
    with pytest.raises(ValidationError):
        PaddleOCRAdapterConfig(engine="onnxruntime")
