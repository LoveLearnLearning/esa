# backend/agent/rag/tests/test_official_config.py

"""验证 `official_config` 相关行为与回归场景。"""

from backend.agent.rag.retrieval.contracts import RetrievalConfig
from backend.agent.rag.cli.index import _retrieval_config
from backend.core.utils import config


def test_official_rag_identity_and_retrieval_defaults_are_frozen() -> None:
    """验证 `official_rag_identity_and_retrieval_defaults_are_frozen` 场景。"""
    assert config.RAG_COLLECTION_ID == "collection_f645d539e0ae078ba11d7e88"
    assert config.RAG_DEPLOYMENT_ID == "deployment_57fdb5e345322c2181e16ee1"
    assert config.RAG_QDRANT_COLLECTION == "esa_knowledge_unified_qwen3_4b"
    assert config.PERSONAL_KB_QDRANT_COLLECTION == config.RAG_QDRANT_COLLECTION
    assert config.RAG_EMBEDDING_DIMENSION == 2560
    assert config.RAG_FUSION_METHOD == "dense"
    assert config.RAG_DENSE_WEIGHT == 1.0
    assert config.RAG_RERANKER_ENABLED is False
    assert config.RAG_METADATA_PROJECTION_MODE == "rule"
    assert config.RAG_DENSE_LIMIT == 100
    assert config.RAG_BM25_BODY_LIMIT == 100
    assert config.RAG_BM25_HEADING_LIMIT == 100
    assert config.RAG_RRF_LIMIT == 100
    assert config.RAG_RERANK_LIMIT == 50
    assert config.RAG_FINAL_LIMIT == 5
    assert config.RAG_MAX_CONTEXT_TOKENS == 16_384


def test_retrieval_config_defaults_match_central_config() -> None:
    """核心检索默认值与集中配置保持一致。"""
    defaults = RetrievalConfig()
    assert defaults.dense_limit == config.RAG_DENSE_LIMIT
    assert defaults.bm25_body_limit == config.RAG_BM25_BODY_LIMIT
    assert defaults.bm25_heading_limit == config.RAG_BM25_HEADING_LIMIT
    assert defaults.rrf_limit == config.RAG_RRF_LIMIT
    assert defaults.rerank_limit == config.RAG_RERANK_LIMIT
    assert defaults.reranker_batch_size == config.RAG_RERANKER_BATCH_SIZE
    assert defaults.final_limit == config.RAG_FINAL_LIMIT
    assert defaults.rrf_k == config.RAG_RRF_K
    assert defaults.section_window == config.RAG_SECTION_WINDOW
    assert defaults.max_context_tokens == config.RAG_MAX_CONTEXT_TOKENS
    assert defaults.rerank_threshold == config.RAG_RERANK_THRESHOLD
    assert defaults.fusion_method == config.RAG_FUSION_METHOD
    assert defaults.dense_weight == config.RAG_DENSE_WEIGHT
    assert defaults.lexical_body_weight == config.RAG_LEXICAL_BODY_WEIGHT
    assert defaults.lexical_gate_enabled == config.RAG_LEXICAL_GATE_ENABLED
    assert defaults.reranker_enabled == config.RAG_RERANKER_ENABLED


def test_cli_can_explicitly_enable_reranker_without_changing_default() -> None:
    assert _retrieval_config().reranker_enabled is False
    assert _retrieval_config(reranker_enabled=True).reranker_enabled is True
