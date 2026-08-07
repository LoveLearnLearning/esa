# backend/core/utils/config.py

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from backend.agent.rag.paths import workspace_root

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

# ------------- rag ---------------

RAG_WORKSPACE_ROOT = workspace_root()

# collection and deployment
RAG_COLLECTION_MANIFEST_PATH: Path = (
    RAG_WORKSPACE_ROOT
    / "artifacts/chunk/collections/collection_bc7a6054e159eb7346e94df0/manifest.json"
)
RAG_INDEX_DEPLOYMENT_ROOT: Path = RAG_WORKSPACE_ROOT / "artifacts/rag/indexes"

# qdrant
RAG_QDRANT_BASE_URL: str = "http://127.0.0.1:6333"
RAG_QDRANT_COLLECTION: str = "rag_qwen3_embedding_4b_v2"
RAG_QDRANT_TIMEOUT: float = 30.0
RAG_QDRANT_UPSERT_BATCH_SIZE: int = 64

# embedding
EmbeddingBackend = Literal["reference", "transformers", "vllm"]
RAG_EMBEDDING_BACKEND: EmbeddingBackend = "transformers"
RAG_EMBEDDING_MODEL_PATH: str = "/home/qwq/models/Qwen3-Embedding-4B"
RAG_EMBEDDING_BASE_URL: str | None = None
RAG_EMBEDDING_DEVICE: str = "cuda"
RAG_EMBEDDING_DIMENSION: int = 2560
RAG_EMBEDDING_MAX_LENGTH: int = 8192
RAG_EMBEDDING_BATCH_SIZE: int = 8
RAG_EMBEDDING_TIMEOUT: float = 120.0

# reranker
RerankerBackend = Literal["none", "transformers", "vllm"]
RAG_RERANKER_BACKEND: RerankerBackend = "transformers"
RAG_RERANKER_MODEL_PATH: str = "/home/qwq/models/Qwen3-Reranker-4B"
RAG_RERANKER_BASE_URL: str | None = None
RAG_RERANKER_DEVICE: str = "cuda"
RAG_RERANKER_MAX_LENGTH: int = 8192
RAG_RERANKER_TIMEOUT: float = 120.0

# retrieval
RAG_DENSE_LIMIT: int = 20
RAG_BM25_BODY_LIMIT: int = 20
RAG_BM25_HEADING_LIMIT: int = 20
RAG_RRF_LIMIT: int = 30
RAG_RERANK_LIMIT: int = 10
RAG_FINAL_LIMIT: int = 5
RAG_RRF_K: int = 60
RAG_SECTION_WINDOW: int = 1
RAG_RERANK_THRESHOLD: float | None = None
