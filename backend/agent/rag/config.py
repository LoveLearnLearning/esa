# backend/agent/rag/config.py

from __future__ import annotations

# # debug
# DEBUG_MODE: bool = True

# # collection and deployment
# COLLECTION_MANIFEST_PATH: Path = (
#     WORKSPACE_ROOT
#     / "artifacts/chunk/collections/collection_bc7a6054e159eb7346e94df0/manifest.json"
# )
# INDEX_DEPLOYMENT_ROOT: Path = WORKSPACE_ROOT / "artifacts/rag/indexes"

# # qdrant
# QDRANT_BASE_URL: str = "http://127.0.0.1:6333"
# QDRANT_COLLECTION: str = "rag_qwen3_embedding_4b_v2"
# QDRANT_TIMEOUT: float = 30.0
# QDRANT_UPSERT_BATCH_SIZE: int = 64

# # embedding
# EmbeddingBackend = Literal["reference", "transformers", "vllm"]
# EMBEDDING_BACKEND: EmbeddingBackend = "transformers"
# EMBEDDING_MODEL_PATH: str = "/home/qwq/models/Qwen3-Embedding-4B"
# EMBEDDING_BASE_URL: str | None = None
# EMBEDDING_DEVICE: str = "cuda"
# EMBEDDING_DIMENSION: int = 2560
# EMBEDDING_MAX_LENGTH: int = 8192
# EMBEDDING_BATCH_SIZE: int = 8
# EMBEDDING_TIMEOUT: float = 120.0

# # reranker
# RerankerBackend = Literal["none", "transformers", "vllm"]
# RERANKER_BACKEND: RerankerBackend = "transformers"
# RERANKER_MODEL_PATH: str = "/home/qwq/models/Qwen3-Reranker-4B"
# RERANKER_BASE_URL: str | None = None
# RERANKER_DEVICE: str = "cuda"
# RERANKER_MAX_LENGTH: int = 8192
# RERANKER_TIMEOUT: float = 120.0

# # retrieval
# DENSE_LIMIT: int = 20
# BM25_BODY_LIMIT: int = 20
# BM25_HEADING_LIMIT: int = 20
# RRF_LIMIT: int = 30
# RERANK_LIMIT: int = 10
# FINAL_LIMIT: int = 5
# RRF_K: int = 60
# SECTION_WINDOW: int = 1
# RERANK_THRESHOLD: float | None = None
