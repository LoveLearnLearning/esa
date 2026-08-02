# backend/core/utils/config.py

# debug
from vllm.config.cache import CacheDType
from vllm.config.model import ModelDType
from vllm.model_executor.layers.quantization import QuantizationMethods

DEBUG_MODE: bool = True

# model
MODEL_PATH: str = "/remote_dir/home/chenxuzhao/models/Qwen3.5-9B"
MODEL_DTYPE: ModelDType = "bfloat16"
MODEL_KV_CACHE_DTYPE: CacheDType = "auto"
MODEL_GPU_MEMORY_UTILIZATION: float = 0.95
MODEL_MAX_MODEL_LENGTH: int = 65536
MODEL_MAX_NUM_SEQS: int = 4
MODEL_QUANTIZATION: QuantizationMethods | None = None
MODEL_TENSOR_PARALLEL_SIZE: int = 2
