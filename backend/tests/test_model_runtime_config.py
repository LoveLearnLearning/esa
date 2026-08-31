from __future__ import annotations

import json
import os
import subprocess
import sys


_MODEL_ENV_NAMES = (
    "ESA_MODEL_TENSOR_PARALLEL_SIZE",
    "ESA_MODEL_PIPELINE_PARALLEL_SIZE",
    "ESA_MODEL_ENFORCE_EAGER",
    "ESA_MODEL_PERFORMANCE_MODE",
    "ESA_MODEL_LORA_FULLY_SHARDED",
    "ESA_MODEL_LORA_SPECIALIZE_ACTIVE",
)


def _load_model_runtime_config(**overrides: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for name in _MODEL_ENV_NAMES:
        env.pop(name, None)
    env.update(overrides)
    code = """
import json
from backend.core.utils.config import (
    MODEL_ENFORCE_EAGER,
    MODEL_LORA_FULLY_SHARDED,
    MODEL_LORA_SPECIALIZE_ACTIVE,
    MODEL_PIPELINE_PARALLEL_SIZE,
    MODEL_PERFORMANCE_MODE,
    MODEL_TENSOR_PARALLEL_SIZE,
)
print(json.dumps({
    "tensor_parallel_size": MODEL_TENSOR_PARALLEL_SIZE,
    "pipeline_parallel_size": MODEL_PIPELINE_PARALLEL_SIZE,
    "enforce_eager": MODEL_ENFORCE_EAGER,
    "performance_mode": MODEL_PERFORMANCE_MODE,
    "fully_sharded_loras": MODEL_LORA_FULLY_SHARDED,
    "specialize_active_lora": MODEL_LORA_SPECIALIZE_ACTIVE,
}))
"""
    return subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_model_runtime_optimization_defaults() -> None:
    result = _load_model_runtime_config()

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "tensor_parallel_size": 2,
        "pipeline_parallel_size": 3,
        "enforce_eager": False,
        "performance_mode": "interactivity",
        "fully_sharded_loras": False,
        "specialize_active_lora": True,
    }


def test_model_runtime_optimization_overrides() -> None:
    result = _load_model_runtime_config(
        ESA_MODEL_TENSOR_PARALLEL_SIZE="4",
        ESA_MODEL_PIPELINE_PARALLEL_SIZE="1",
        ESA_MODEL_ENFORCE_EAGER="yes",
        ESA_MODEL_PERFORMANCE_MODE="throughput",
        ESA_MODEL_LORA_FULLY_SHARDED="1",
        ESA_MODEL_LORA_SPECIALIZE_ACTIVE="off",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "tensor_parallel_size": 4,
        "pipeline_parallel_size": 1,
        "enforce_eager": True,
        "performance_mode": "throughput",
        "fully_sharded_loras": True,
        "specialize_active_lora": False,
    }


def test_model_runtime_rejects_invalid_performance_mode() -> None:
    result = _load_model_runtime_config(ESA_MODEL_PERFORMANCE_MODE="fastest")

    assert result.returncode != 0
    assert "ESA_MODEL_PERFORMANCE_MODE" in result.stderr


def test_model_runtime_rejects_non_positive_parallel_size() -> None:
    result = _load_model_runtime_config(ESA_MODEL_PIPELINE_PARALLEL_SIZE="0")

    assert result.returncode != 0
    assert "ESA_MODEL_PIPELINE_PARALLEL_SIZE" in result.stderr
