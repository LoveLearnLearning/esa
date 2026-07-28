# backend/core/utils/config.py

# debug
from vllm.config.model import ModelDType
from vllm.model_executor.layers.quantization import QuantizationMethods

DEBUG_MODE: bool = True

# model
MODEL_PATH: str = "Qwen/Qwen3.5-9B"
MODEL_DTYPE: ModelDType = "bfloat16"
MODEL_KV_CACHE_DTYPE: str = "fp8"
MODEL_GPU_MEMORY_UTILIZATION: float = 0.95
MODEL_MAX_MODEL_LENGTH: int = 32768
MODEL_MAX_NUM_SEQS: int = 1
MODEL_QUANTIZATION: QuantizationMethods = "bitsandbytes"
