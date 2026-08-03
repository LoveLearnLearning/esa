# backend/agent/rag/indexing/deployment.py

"""

这个文件干什么：RAG 索引部署 manifest 契约与确定性读写。

直白点说就是：把一次可复用索引部署的集合、模型、配置和哈希写进清单，并负责安全读写。

RAG 索引部署 manifest 契约与确定性读写。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from ..chunk.serializer import save_json
from ..fingerprints import configuration_sha256
from .service import IndexGeneration

EmbeddingBackend = Literal["reference", "transformers", "vllm"]


@dataclass(frozen=True)
class IndexDeployment:
    """记录一个索引代次在具体 Qdrant Collection 中的部署位置。"""

    schema_version: str
    deployment_id: str
    generation: IndexGeneration
    qdrant_base_url: str
    qdrant_collection: str
    embedding_backend: EmbeddingBackend
    embedding_model_name: str
    embedding_base_url: str | None

    @classmethod
    def create(
        cls,
        generation: IndexGeneration,
        *,
        qdrant_base_url: str,
        qdrant_collection: str,
        embedding_backend: EmbeddingBackend,
        embedding_model_name: str,
        embedding_base_url: str | None,
    ) -> IndexDeployment:
        """根据代次与部署位置生成稳定 deployment_id。"""

        identity = {
            "schema_version": "rag-index-deployment-0.1",
            "index_generation_id": generation.index_generation_id,
            "qdrant_base_url": qdrant_base_url.rstrip("/"),
            "qdrant_collection": qdrant_collection,
            "embedding_backend": embedding_backend,
            "embedding_model_name": embedding_model_name,
            "embedding_base_url": (
                embedding_base_url.rstrip("/") if embedding_base_url else None
            ),
        }
        return cls(
            schema_version="rag-index-deployment-0.1",
            deployment_id=f"deployment_{configuration_sha256(identity)[:24]}",
            generation=generation,
            qdrant_base_url=str(identity["qdrant_base_url"]),
            qdrant_collection=qdrant_collection,
            embedding_backend=embedding_backend,
            embedding_model_name=embedding_model_name,
            embedding_base_url=(
                str(identity["embedding_base_url"])
                if identity["embedding_base_url"] is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """返回可序列化且字段稳定的部署 manifest。"""

        payload = asdict(self)
        payload["generation"] = self.generation.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> IndexDeployment:
        """严格加载部署 manifest，并重新计算身份防止静默篡改。"""

        expected = {
            "schema_version",
            "deployment_id",
            "generation",
            "qdrant_base_url",
            "qdrant_collection",
            "embedding_backend",
            "embedding_model_name",
            "embedding_base_url",
        }
        if set(payload) != expected:
            raise ValueError("index deployment fields do not match schema")
        if payload["schema_version"] != "rag-index-deployment-0.1":
            raise ValueError("unsupported index deployment schema")
        raw_generation = payload["generation"]
        if not isinstance(raw_generation, Mapping):
            raise TypeError("generation must be an object")
        backend = payload["embedding_backend"]
        if backend not in {"reference", "transformers", "vllm"}:
            raise ValueError(
                "embedding_backend must be reference, transformers, or vllm"
            )
        base_url = _required_string(payload, "qdrant_base_url")
        collection = _required_string(payload, "qdrant_collection")
        model_name = _required_string(payload, "embedding_model_name")
        embedding_url = payload["embedding_base_url"]
        if embedding_url is not None and not isinstance(embedding_url, str):
            raise ValueError("embedding_base_url must be a string or null")
        deployment = cls.create(
            IndexGeneration.from_dict(raw_generation),
            qdrant_base_url=base_url,
            qdrant_collection=collection,
            embedding_backend=backend,
            embedding_model_name=model_name,
            embedding_base_url=embedding_url,
        )
        if payload["deployment_id"] != deployment.deployment_id:
            raise ValueError("deployment_id does not match deployment inputs")
        return deployment


def save_deployment(deployment: IndexDeployment, path: Path) -> str:
    """原子保存部署 manifest，并返回文件 SHA-256。"""

    return save_json(deployment.to_dict(), path)


def load_deployment(path: Path) -> IndexDeployment:
    """读取并严格验证部署 manifest。"""

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("index deployment manifest must be an object")
    return IndexDeployment.from_dict(raw)


def _required_string(payload: Mapping[str, object], name: str) -> str:
    """读取必填非空字符串字段。"""

    value = payload[name]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value
