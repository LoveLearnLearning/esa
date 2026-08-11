import os
from pathlib import Path

from backend.agent.rag.collection import load_chunk_collection
from backend.agent.rag.fingerprints import backend_fingerprint
from backend.agent.rag.indexes import QdrantIndex
from backend.agent.rag.indexing import load_deployment
from backend.agent.rag.inference import (
    HashingEmbeddingProvider,
    TransformersEmbeddingProvider,
    TransformersReranker,
    VLLMEmbeddingProvider,
    VLLMReranker,
)
from backend.agent.rag.retrieval.contracts import RetrievalConfig
from backend.agent.rag.retrieval.service import RetrievalService
from backend.core.utils import config


def create_retrieval_service(
    deployment_manifest: Path,
) -> RetrievalService:
    """加载并验证已有部署；这里绝不构建新索引。"""

    deployment = load_deployment(deployment_manifest)
    collection = load_chunk_collection(config.RAG_COLLECTION_MANIFEST_PATH)
    generation = deployment.generation

    if collection.manifest.collection_id != generation.collection_id:
        raise RuntimeError("RAG deployment 与 ChunkCollection ID 不一致")
    if collection.manifest_sha256 != generation.collection_manifest_sha256:
        raise RuntimeError("RAG deployment 与 ChunkCollection SHA-256 不一致")
    if len(collection.chunks) != generation.chunk_count:
        raise RuntimeError("RAG deployment 与 Chunk 数量不一致")

    index = QdrantIndex(
        base_url=deployment.qdrant_base_url,
        collection=deployment.qdrant_collection,
        api_key=os.environ.get("QDRANT_API_KEY"),
        timeout=config.RAG_QDRANT_TIMEOUT,
        upsert_batch_size=config.RAG_QDRANT_UPSERT_BATCH_SIZE,
    )
    if index.configuration_fingerprint != generation.index_fingerprint:
        raise RuntimeError("RAG deployment 与 Qdrant 索引配置不一致")
    index.validate_existing(
        generation.dense_dimension,
        generation.index_generation_id,
        generation.chunk_count,
    )

    if config.RAG_EMBEDDING_BACKEND != deployment.embedding_backend:
        raise RuntimeError(
            "RAG_EMBEDDING_BACKEND does not match the frozen deployment manifest"
        )
    if deployment.embedding_backend == "reference":
        embedding = HashingEmbeddingProvider(
            dimensions=generation.dense_dimension,
            model_name=deployment.embedding_model_name,
        )
    elif deployment.embedding_backend == "transformers":
        embedding = TransformersEmbeddingProvider(
            model_name=deployment.embedding_model_name,
            load_path=config.RAG_EMBEDDING_MODEL_PATH,
            device=config.RAG_EMBEDDING_DEVICE,
            dimension=generation.dense_dimension,
            max_length=config.RAG_EMBEDDING_MAX_LENGTH,
            batch_size=config.RAG_EMBEDDING_BATCH_SIZE,
        )
    else:
        base_url = config.RAG_EMBEDDING_BASE_URL or deployment.embedding_base_url
        if not base_url:
            raise RuntimeError("vLLM embedding deployment requires a base URL")
        embedding = VLLMEmbeddingProvider(
            base_url=base_url,
            model_name=deployment.embedding_model_name,
            api_key=os.environ.get("VLLM_API_KEY"),
            timeout=config.RAG_EMBEDDING_TIMEOUT,
        )
    embedding_fingerprint = backend_fingerprint(
        embedding,
        {
            "backend": type(embedding).__qualname__,
            "model_name": embedding.model_name,
        },
    )
    if embedding_fingerprint != generation.embedding_fingerprint:
        raise RuntimeError("RAG deployment 与 Embedding 配置不一致")

    if not config.RAG_RERANKER_ENABLED:
        reranker = None
    elif config.RAG_RERANKER_BACKEND == "transformers":
        reranker = TransformersReranker(
            model_name="Qwen/Qwen3-Reranker-4B",
            load_path=config.RAG_RERANKER_MODEL_PATH,
            device=config.RAG_RERANKER_DEVICE,
            max_length=config.RAG_RERANKER_MAX_LENGTH,
        )
    elif config.RAG_RERANKER_BACKEND == "vllm":
        if not config.RAG_RERANKER_BASE_URL:
            raise RuntimeError("vLLM reranker requires RAG_RERANKER_BASE_URL")
        reranker = VLLMReranker(
            base_url=config.RAG_RERANKER_BASE_URL,
            model_name=config.RAG_RERANKER_MODEL_PATH,
            api_key=os.environ.get("VLLM_API_KEY"),
            timeout=config.RAG_RERANKER_TIMEOUT,
        )
    else:
        raise RuntimeError("enabled reranker requires transformers or vllm backend")
    retrieval_config = RetrievalConfig(
        dense_limit=config.RAG_DENSE_LIMIT,
        bm25_body_limit=config.RAG_BM25_BODY_LIMIT,
        bm25_heading_limit=config.RAG_BM25_HEADING_LIMIT,
        rrf_limit=config.RAG_RRF_LIMIT,
        rerank_limit=config.RAG_RERANK_LIMIT,
        reranker_batch_size=config.RAG_RERANKER_BATCH_SIZE,
        final_limit=config.RAG_FINAL_LIMIT,
        rrf_k=config.RAG_RRF_K,
        section_window=config.RAG_SECTION_WINDOW,
        max_context_tokens=config.RAG_MAX_CONTEXT_TOKENS,
        rerank_threshold=config.RAG_RERANK_THRESHOLD,
        fusion_method=config.RAG_FUSION_METHOD,
        dense_weight=config.RAG_DENSE_WEIGHT,
        lexical_body_weight=config.RAG_LEXICAL_BODY_WEIGHT,
        lexical_gate_enabled=config.RAG_LEXICAL_GATE_ENABLED,
        reranker_enabled=config.RAG_RERANKER_ENABLED,
        reranker_prior_weight=config.RAG_RERANKER_PRIOR_WEIGHT,
    )
    return RetrievalService(
        collection=collection,
        index=index,
        embedding=embedding,
        reranker=reranker,
        config=retrieval_config,
    )
