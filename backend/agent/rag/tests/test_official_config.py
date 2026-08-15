# backend/agent/rag/tests/test_official_config.py

"""验证 `official_config` 相关行为与回归场景。"""

from backend.core.utils import config


def test_official_rag_identity_and_retrieval_defaults_are_frozen() -> None:
    """验证 `official_rag_identity_and_retrieval_defaults_are_frozen` 场景。"""
    assert config.RAG_COLLECTION_ID == "collection_e55166f798ef1c361c72de9a"
    assert config.RAG_DEPLOYMENT_ID == "deployment_357bd9c84d8404fae42c2740"
    assert config.RAG_QDRANT_COLLECTION == "rag_qwen3_embedding_4b_v2"
    assert config.RAG_EMBEDDING_DIMENSION == 2560
    assert config.RAG_FUSION_METHOD == "dense"
    assert config.RAG_DENSE_WEIGHT == 1.0
    assert config.RAG_RERANKER_ENABLED is False
    assert config.RAG_RERANK_LIMIT == 20
    assert config.RAG_FINAL_LIMIT == 5
    assert config.RAG_MAX_CONTEXT_TOKENS == 8192
