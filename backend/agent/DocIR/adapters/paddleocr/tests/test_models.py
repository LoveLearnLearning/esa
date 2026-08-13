from pathlib import Path

import pytest
from pydantic import ValidationError

from ..models import PaddleOCRAdapterConfig


def test_config_requires_local_paddle_gpu_profile() -> None:
    config = PaddleOCRAdapterConfig()
    assert config.device == "gpu:0"
    assert config.engine == "paddle"
    assert config.model_cache_dir == Path("/tmp/esa-paddleocr-cache")
    with pytest.raises(ValidationError):
        PaddleOCRAdapterConfig(device="cpu")
    with pytest.raises(ValidationError):
        PaddleOCRAdapterConfig(engine="onnxruntime")
