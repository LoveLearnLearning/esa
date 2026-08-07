# backend/core/utils/config.py

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # debug
    from vllm.config.cache import CacheDType
    from vllm.config.model import ModelDType
    from vllm.model_executor.layers.quantization import QuantizationMethods

DEBUG_MODE: bool = True

SEARXNG_BASE_URL = "http://115.29.197.244:8888"

# model
MODEL_PATH: str = "/remote_dir/home/chenxuzhao/models/DeepSeek-V4-Flash-0731"
MODEL_ADAPTER: str = "deepseek_v4"
MODEL_DTYPE: ModelDType = "bfloat16"
MODEL_KV_CACHE_DTYPE: CacheDType = "fp8_ds_mla"
MODEL_GPU_MEMORY_UTILIZATION: float = 0.85
MODEL_MAX_MODEL_LENGTH: int = 40960
MODEL_MAX_NUM_SEQS: int = 16
MODEL_QUANTIZATION: QuantizationMethods | None = None
MODEL_TENSOR_PARALLEL_SIZE: int = 4

# agent
AGENT_LOOP_TIME: int = 10
