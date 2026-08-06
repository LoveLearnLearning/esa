# backend/core/utils/config.py

# debug
from vllm.config.cache import CacheDType
from vllm.config.model import ModelDType
from vllm.model_executor.layers.quantization import QuantizationMethods

DEBUG_MODE: bool = True

# model
MODEL_PATH: str = "/remote_dir/home/chenxuzhao/models/Qwen3.5-122B-A10B"
# auto 会根据模型路径识别；若本地目录名未包含 deepseek-v4，请设为 deepseek_v4。
MODEL_ADAPTER: str = "auto"
MODEL_DTYPE: ModelDType = "bfloat16"
MODEL_KV_CACHE_DTYPE: CacheDType = "auto"
MODEL_GPU_MEMORY_UTILIZATION: float = 0.95
MODEL_MAX_MODEL_LENGTH: int = 40960
MODEL_MAX_NUM_SEQS: int = 16
MODEL_QUANTIZATION: QuantizationMethods | None = None
MODEL_TENSOR_PARALLEL_SIZE: int = 4

# agent
AGENT_LOOP_TIME: int = 10
