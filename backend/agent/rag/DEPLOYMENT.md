# Frozen RAG deployment and Agent contracts

The production baseline is frozen to the following identity. Runtime artifacts
remain outside Git and must be provisioned before `RAG_ENABLED=true`.

- Collection: `collection_e55166f798ef1c361c72de9a` (11 documents, 941 chunks)
- Deployment: `deployment_357bd9c84d8404fae42c2740`
- Qdrant collection: `rag_qwen3_embedding_4b_v2`
- Embedding: Qwen3-Embedding-4B, 2560 dimensions
- Retrieval: dense-only, top 20 candidates, top 5 final results, 8192 context tokens
- Reranker: disabled; `rerank_limit=20` remains part of the stable config schema

The authoritative environment mapping is `backend/core/utils/config.py`; the
deployable template is `.env.example`. A deployment manifest owns the indexed
embedding identity, while `RAG_EMBEDDING_MODEL_PATH` may point at an equivalent
local model copy used to load it.

## B1/B2 freeze

`get_knowledge_base_stats` is B1 v1 and `retrieve_knowledge` is B2 v1. Their
exact top-level and result key order is declared in `agent_api.py` and enforced
by `tests/test_agent_api.py`. In particular, B2 `results[].location` is present,
and `results[].page` is populated only for a `kind=page` locator. Contract
changes require a new version, updated real fixtures, and regenerated training
data; they must not be introduced as silent additive fields.
