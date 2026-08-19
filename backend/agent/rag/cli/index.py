# backend/agent/rag/cli/index.py

"""

这个文件干什么：构建、校验和查询一个可重启验证的 Qdrant 索引部署。

直白点说就是：让用户通过命令行构建索引、检查索引能否重启复用，并实际发起查询。

构建、校验和查询一个可重启验证的 Qdrant 索引部署。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
from pathlib import Path
from typing import Any, Literal

from backend.core.utils import config as core_config

from ..collection import LoadedChunkCollection, load_chunk_collection
from ..fingerprints import backend_fingerprint
from ..indexes import QdrantIndex
from ..indexing import (
    EmbeddingBackend,
    IndexBuildResult,
    IndexDeployment,
    IndexingService,
    load_deployment,
    save_deployment,
)
from ..inference import (
    HashingEmbeddingProvider,
    TransformersEmbeddingProvider,
    TransformersReranker,
    VLLMEmbeddingProvider,
    VLLMReranker,
)
from ..retrieval.contracts import RetrievalConfig
from ..retrieval.service import RetrievalService

RerankerBackend = Literal["none", "transformers", "vllm"]


def build_deployment(arguments: argparse.Namespace) -> Path:
    """构建或复用一个完整索引代次，并保存部署 manifest。"""

    collection = load_chunk_collection(arguments.manifest)
    embedding = _embedding_provider(
        arguments.embedding_backend,
        arguments.embedding_model,
        arguments.embedding_url,
        arguments.embedding_dimension,
    )
    index = _qdrant_index(arguments.qdrant_url, arguments.collection)
    result = IndexingService(collection, index, embedding).build()
    deployment = IndexDeployment.create(
        result.generation,
        qdrant_base_url=arguments.qdrant_url,
        qdrant_collection=arguments.collection,
        embedding_backend=arguments.embedding_backend,
        embedding_model_name=embedding.model_name,
        embedding_base_url=(
            arguments.embedding_url if arguments.embedding_backend == "vllm" else None
        ),
    )
    deployment_root = arguments.output / deployment.deployment_id
    deployment_root.mkdir(parents=True, exist_ok=True)
    manifest_path = deployment_root / "manifest.json"
    save_deployment(deployment, manifest_path)
    _print_build_result(manifest_path, deployment, result)
    return manifest_path


def verify_deployment(arguments: argparse.Namespace) -> IndexDeployment:
    """不重新编码文本，校验重启后的 Qdrant 代次和 Point 数量。"""

    deployment = load_deployment(arguments.deployment_manifest)
    collection = load_chunk_collection(arguments.manifest)
    _validate_collection_identity(collection, deployment)
    index = _qdrant_index(
        deployment.qdrant_base_url,
        deployment.qdrant_collection,
    )
    if index.configuration_fingerprint != deployment.generation.index_fingerprint:
        raise ValueError("Qdrant configuration does not match index generation")
    index.validate_existing(
        deployment.generation.dense_dimension,
        deployment.generation.index_generation_id,
        deployment.generation.chunk_count,
    )
    print(f"deployment_id={deployment.deployment_id}")
    print(f"index_generation_id={deployment.generation.index_generation_id}")
    print(f"points={deployment.generation.chunk_count} status=ready")
    return deployment


def query_deployment(arguments: argparse.Namespace) -> dict[str, Any]:
    """校验部署后执行 Dense、BM25 Body、BM25 Heading 和 RRF 查询。"""

    deployment = verify_deployment(arguments)
    collection = load_chunk_collection(arguments.manifest)
    embedding = _embedding_provider(
        deployment.embedding_backend,
        deployment.embedding_model_name,
        deployment.embedding_base_url,
        deployment.generation.dense_dimension,
    )
    fingerprint = backend_fingerprint(
        embedding,
        {
            "backend": type(embedding).__qualname__,
            "model_name": embedding.model_name,
        },
    )
    if fingerprint != deployment.generation.embedding_fingerprint:
        raise ValueError("Embedding configuration does not match index generation")
    index = _qdrant_index(
        deployment.qdrant_base_url,
        deployment.qdrant_collection,
    )
    reranker = _reranker(
        arguments.reranker_backend,
        arguments.reranker_model,
        arguments.reranker_url,
    )
    response = RetrievalService(
        collection,
        index,
        embedding,
        reranker=reranker,
        config=_retrieval_config(),
    ).search(arguments.query)
    payload = dataclasses.asdict(response)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return payload


def _embedding_provider(
    backend: EmbeddingBackend,
    model_name: str,
    base_url: str | None,
    dense_dimension: int | None,
) -> HashingEmbeddingProvider | TransformersEmbeddingProvider | VLLMEmbeddingProvider:
    """根据显式后端配置创建 Embedding Provider。"""

    if backend == "reference":
        return HashingEmbeddingProvider(model_name=model_name)
    if backend == "transformers":
        return TransformersEmbeddingProvider(
            model_name=model_name,
            device=core_config.RAG_EMBEDDING_DEVICE,
            dimension=dense_dimension or core_config.RAG_EMBEDDING_DIMENSION,
            max_length=core_config.RAG_EMBEDDING_MAX_LENGTH,
            batch_size=core_config.RAG_EMBEDDING_BATCH_SIZE,
        )
    if not base_url:
        raise ValueError("--embedding-url is required for vllm backend")
    return VLLMEmbeddingProvider(
        base_url=base_url,
        model_name=model_name,
        api_key=os.environ.get("VLLM_API_KEY"),
        timeout=core_config.RAG_EMBEDDING_TIMEOUT,
    )


def _qdrant_index(base_url: str, collection: str) -> QdrantIndex:
    """使用环境变量中的可选密钥创建 Qdrant 适配器。"""

    return QdrantIndex(
        base_url=base_url,
        collection=collection,
        api_key=os.environ.get("QDRANT_API_KEY"),
        timeout=core_config.RAG_QDRANT_TIMEOUT,
        upsert_batch_size=core_config.RAG_QDRANT_UPSERT_BATCH_SIZE,
    )


def _reranker(
    backend: RerankerBackend,
    model_name: str,
    base_url: str | None,
) -> TransformersReranker | VLLMReranker | None:
    """根据查询期显式配置创建可选 Reranker。"""

    if backend == "none":
        return None
    if backend == "transformers":
        return TransformersReranker(
            model_name=model_name,
            device=core_config.RAG_RERANKER_DEVICE,
            max_length=core_config.RAG_RERANKER_MAX_LENGTH,
        )
    if not base_url:
        raise ValueError("--reranker-url is required for vllm backend")
    return VLLMReranker(
        base_url=base_url,
        model_name=model_name,
        api_key=os.environ.get("VLLM_API_KEY"),
        timeout=core_config.RAG_RERANKER_TIMEOUT,
    )


def _retrieval_config() -> RetrievalConfig:
    """把集中配置转换为核心检索链的稳定配置对象。"""

    return RetrievalConfig(
        dense_limit=core_config.RAG_DENSE_LIMIT,
        bm25_body_limit=core_config.RAG_BM25_BODY_LIMIT,
        bm25_heading_limit=core_config.RAG_BM25_HEADING_LIMIT,
        rrf_limit=core_config.RAG_RRF_LIMIT,
        rerank_limit=core_config.RAG_RERANK_LIMIT,
        reranker_batch_size=core_config.RAG_RERANKER_BATCH_SIZE,
        final_limit=core_config.RAG_FINAL_LIMIT,
        rrf_k=core_config.RAG_RRF_K,
        section_window=core_config.RAG_SECTION_WINDOW,
        max_context_tokens=core_config.RAG_MAX_CONTEXT_TOKENS,
        rerank_threshold=core_config.RAG_RERANK_THRESHOLD,
        fusion_method=core_config.RAG_FUSION_METHOD,
        dense_weight=core_config.RAG_DENSE_WEIGHT,
        lexical_body_weight=core_config.RAG_LEXICAL_BODY_WEIGHT,
        lexical_gate_enabled=core_config.RAG_LEXICAL_GATE_ENABLED,
        reranker_enabled=core_config.RAG_RERANKER_ENABLED,
        reranker_prior_weight=core_config.RAG_RERANKER_PRIOR_WEIGHT,
    )


def _validate_collection_identity(
    collection: LoadedChunkCollection,
    deployment: IndexDeployment,
) -> None:
    """确认部署 manifest 仍指向同一份权威 ChunkCollection。"""

    generation = deployment.generation
    if collection.manifest.collection_id != generation.collection_id:
        raise ValueError("deployment collection_id does not match ChunkCollection")
    if collection.manifest_sha256 != generation.collection_manifest_sha256:
        raise ValueError("deployment manifest SHA-256 does not match ChunkCollection")
    if len(collection.chunks) != generation.chunk_count:
        raise ValueError("deployment chunk_count does not match ChunkCollection")


def _print_build_result(
    manifest_path: Path,
    deployment: IndexDeployment,
    result: IndexBuildResult,
) -> None:
    """输出适合脚本读取的构建摘要。"""

    print(f"deployment_manifest={manifest_path}")
    print(f"deployment_id={deployment.deployment_id}")
    print(f"index_generation_id={deployment.generation.index_generation_id}")
    print(f"points={deployment.generation.chunk_count}")
    print(f"indexed={str(result.indexed).lower()}")


def _add_manifest_argument(parser: argparse.ArgumentParser) -> None:
    """添加 `manifest argument` 相关数据。"""
    parser.add_argument(
        "--manifest",
        type=Path,
        default=core_config.RAG_COLLECTION_MANIFEST_PATH,
    )


def _add_deployment_argument(parser: argparse.ArgumentParser) -> None:
    """添加 `deployment argument` 相关数据。"""
    parser.add_argument("--deployment-manifest", type=Path, required=True)
    _add_manifest_argument(parser)


def _parser() -> argparse.ArgumentParser:
    """定义索引生命周期命令行接口。"""

    parser = argparse.ArgumentParser(description="管理 RAG Qdrant 索引代次")
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="构建或复用索引代次")
    _add_manifest_argument(build)
    build.add_argument(
        "--output",
        type=Path,
        default=core_config.RAG_INDEX_DEPLOYMENT_ROOT,
    )
    build.add_argument("--qdrant-url", default=core_config.RAG_QDRANT_BASE_URL)
    build.add_argument("--collection", default=core_config.RAG_QDRANT_COLLECTION)
    build.add_argument(
        "--embedding-backend",
        choices=("reference", "transformers", "vllm"),
        default=core_config.RAG_EMBEDDING_BACKEND,
    )
    build.add_argument(
        "--embedding-model",
        default=core_config.RAG_EMBEDDING_MODEL_PATH,
    )
    build.add_argument(
        "--embedding-url",
        default=core_config.RAG_EMBEDDING_BASE_URL,
    )
    build.add_argument(
        "--embedding-dimension",
        type=int,
        default=core_config.RAG_EMBEDDING_DIMENSION,
    )
    build.set_defaults(handler=build_deployment)

    verify = commands.add_parser("verify", help="验证重启后的索引完整性")
    _add_deployment_argument(verify)
    verify.set_defaults(handler=verify_deployment)

    query = commands.add_parser("query", help="执行三路召回和 RRF 查询")
    _add_deployment_argument(query)
    query.add_argument("--query", required=True)
    query.add_argument(
        "--reranker-backend",
        choices=("none", "transformers", "vllm"),
        default=core_config.RAG_RERANKER_BACKEND,
    )
    query.add_argument(
        "--reranker-model",
        default=core_config.RAG_RERANKER_MODEL_PATH,
    )
    query.add_argument(
        "--reranker-url",
        default=core_config.RAG_RERANKER_BASE_URL,
    )
    query.set_defaults(handler=query_deployment)
    return parser


def main(argv: list[str] | None = None) -> int:
    """运行当前模块的命令行入口。"""
    arguments = _parser().parse_args(argv)
    arguments.handler(arguments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
