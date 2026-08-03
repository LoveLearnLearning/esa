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
from ..paths import WORKSPACE_ROOT
from ..retrieval.service import RetrievalService

DEFAULT_MANIFEST = (
    WORKSPACE_ROOT
    / "artifacts/chunk/collections/collection_bc7a6054e159eb7346e94df0/manifest.json"
)
DEFAULT_OUTPUT = WORKSPACE_ROOT / "artifacts/rag/indexes"
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
            arguments.embedding_url
            if arguments.embedding_backend == "vllm"
            else None
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
            dimension=dense_dimension or 2560,
        )
    if not base_url:
        raise ValueError("--embedding-url is required for vllm backend")
    return VLLMEmbeddingProvider(
        base_url=base_url,
        model_name=model_name,
        api_key=os.environ.get("VLLM_API_KEY"),
    )


def _qdrant_index(base_url: str, collection: str) -> QdrantIndex:
    """使用环境变量中的可选密钥创建 Qdrant 适配器。"""

    return QdrantIndex(
        base_url=base_url,
        collection=collection,
        api_key=os.environ.get("QDRANT_API_KEY"),
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
        return TransformersReranker(model_name=model_name)
    if not base_url:
        raise ValueError("--reranker-url is required for vllm backend")
    return VLLMReranker(
        base_url=base_url,
        model_name=model_name,
        api_key=os.environ.get("VLLM_API_KEY"),
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
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)


def _add_deployment_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--deployment-manifest", type=Path, required=True)
    _add_manifest_argument(parser)


def _parser() -> argparse.ArgumentParser:
    """定义索引生命周期命令行接口。"""

    parser = argparse.ArgumentParser(description="管理 RAG Qdrant 索引代次")
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="构建或复用索引代次")
    _add_manifest_argument(build)
    build.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    build.add_argument("--qdrant-url", required=True)
    build.add_argument("--collection", required=True)
    build.add_argument(
        "--embedding-backend",
        choices=("reference", "transformers", "vllm"),
        default="reference",
    )
    build.add_argument(
        "--embedding-model",
        default="reference-hashing-embedding-0.1",
    )
    build.add_argument("--embedding-url")
    build.add_argument("--embedding-dimension", type=int, default=2560)
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
        default="none",
    )
    query.add_argument(
        "--reranker-model",
        default="Qwen/Qwen3-Reranker-4B",
    )
    query.add_argument("--reranker-url")
    query.set_defaults(handler=query_deployment)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    arguments.handler(arguments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
