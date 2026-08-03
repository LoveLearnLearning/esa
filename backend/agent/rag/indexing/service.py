# backend/agent/rag/indexing/service.py

"""

这个文件干什么：把 ChunkCollection 转换为可追踪的索引代次。

直白点说就是：为整批 Chunk 生成向量、写入索引，并记录这次构建属于哪个可追踪代次。

把 ChunkCollection 转换为可追踪的索引代次。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field

from ..collection import LoadedChunkCollection
from ..fingerprints import backend_fingerprint, configuration_sha256
from ..retrieval.contracts import EmbeddingProvider, RetrievalIndex


@dataclass(frozen=True)
class IndexGeneration:
    """一次索引构建的稳定身份及全部关键输入。"""

    schema_version: str
    index_generation_id: str
    collection_id: str
    collection_manifest_sha256: str
    embedding_fingerprint: str
    index_fingerprint: str
    dense_dimension: int
    chunk_count: int

    def __post_init__(self) -> None:
        if self.schema_version != "rag-index-generation-0.1":
            raise ValueError("unsupported index generation schema")
        for name in (
            "collection_manifest_sha256",
            "embedding_fingerprint",
            "index_fingerprint",
        ):
            value = getattr(self, name)
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{name} must be a lowercase SHA-256")
        if self.dense_dimension <= 0:
            raise ValueError("dense_dimension must be positive")
        if self.chunk_count < 0:
            raise ValueError("chunk_count cannot be negative")
        identity = {
            "schema_version": self.schema_version,
            "collection_id": self.collection_id,
            "collection_manifest_sha256": self.collection_manifest_sha256,
            "embedding_fingerprint": self.embedding_fingerprint,
            "index_fingerprint": self.index_fingerprint,
            "dense_dimension": self.dense_dimension,
            "chunk_count": self.chunk_count,
        }
        expected_id = f"index_{configuration_sha256(identity)[:24]}"
        if self.index_generation_id != expected_id:
            raise ValueError("index_generation_id does not match generation inputs")

    def to_dict(self) -> dict[str, str | int]:
        """返回适合写入运行 manifest 的 JSON 数据。"""

        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> IndexGeneration:
        """严格加载机器可读的索引代次。"""

        expected = {
            "schema_version",
            "index_generation_id",
            "collection_id",
            "collection_manifest_sha256",
            "embedding_fingerprint",
            "index_fingerprint",
            "dense_dimension",
            "chunk_count",
        }
        if set(payload) != expected:
            raise ValueError("index generation fields do not match schema")
        string_fields = expected - {"dense_dimension", "chunk_count"}
        if any(
            not isinstance(payload[name], str) or not payload[name]
            for name in string_fields
        ):
            raise ValueError("index generation string fields cannot be blank")
        if payload["schema_version"] != "rag-index-generation-0.1":
            raise ValueError("unsupported index generation schema")
        dense_dimension = payload["dense_dimension"]
        chunk_count = payload["chunk_count"]
        if not isinstance(dense_dimension, int) or dense_dimension <= 0:
            raise ValueError("dense_dimension must be a positive integer")
        if not isinstance(chunk_count, int) or chunk_count < 0:
            raise ValueError("chunk_count must be a non-negative integer")
        return cls(
            schema_version=str(payload["schema_version"]),
            index_generation_id=str(payload["index_generation_id"]),
            collection_id=str(payload["collection_id"]),
            collection_manifest_sha256=str(
                payload["collection_manifest_sha256"]
            ),
            embedding_fingerprint=str(payload["embedding_fingerprint"]),
            index_fingerprint=str(payload["index_fingerprint"]),
            dense_dimension=dense_dimension,
            chunk_count=chunk_count,
        )


@dataclass(frozen=True)
class IndexBuildResult:
    """索引构建结果；indexed=false 表示复用了已有完整代次。"""

    generation: IndexGeneration
    indexed: bool


@dataclass
class IndexingService:
    """只负责生成文档向量、校验矩阵并写入检索索引。"""

    collection: LoadedChunkCollection
    index: RetrievalIndex
    embedding: EmbeddingProvider
    _generation: IndexGeneration | None = field(
        init=False,
        default=None,
        repr=False,
    )

    def build(self) -> IndexBuildResult:
        """幂等构建索引；同一实例的重复调用不会再次编码或写入。"""

        if self._generation is not None:
            return IndexBuildResult(self._generation, indexed=False)

        declared_dimension = _declared_embedding_dimension(self.embedding)
        if declared_dimension is not None:
            generation = self._prepare_generation(declared_dimension)
            if self.index.generation_is_ready(
                generation.index_generation_id,
                len(self.collection.chunks),
            ):
                self._generation = generation
                return IndexBuildResult(generation, indexed=False)

        vectors = self._embed_documents()
        dense_dimension = _validate_vector_matrix(
            vectors,
            expected_count=len(self.collection.chunks),
        )
        if (
            declared_dimension is not None
            and dense_dimension != declared_dimension
        ):
            raise ValueError("embedding output dimension does not match declaration")
        generation = self._make_generation(dense_dimension)
        expected_count = len(self.collection.chunks)
        if declared_dimension is None:
            generation = self._prepare_generation(dense_dimension)
            if self.index.generation_is_ready(
                generation.index_generation_id,
                expected_count,
            ):
                self._generation = generation
                return IndexBuildResult(generation, indexed=False)
        self.index.build(
            self.collection.chunks,
            vectors,
            generation_id=generation.index_generation_id,
        )
        if not self.index.generation_is_ready(
            generation.index_generation_id,
            expected_count,
        ):
            raise RuntimeError("index backend did not persist the complete generation")
        self._generation = generation
        return IndexBuildResult(generation, indexed=True)

    def _prepare_generation(self, dense_dimension: int) -> IndexGeneration:
        """计算代次并让索引后端校验或创建对应结构。"""

        generation = self._make_generation(dense_dimension)
        self.index.prepare(
            dense_dimension,
            generation.index_generation_id,
            len(self.collection.chunks),
        )
        return generation

    def _embed_documents(self) -> list[list[float]]:
        """使用文档编码入口生成全部 Chunk 向量。"""

        embed_documents = getattr(
            self.embedding,
            "embed_documents",
            self.embedding.embed,
        )
        return embed_documents(
            [chunk.dense_text for chunk in self.collection.chunks]
        )

    def _make_generation(self, dense_dimension: int) -> IndexGeneration:
        """根据 Collection 与后端配置生成稳定索引代次。"""

        embedding_fingerprint = backend_fingerprint(
            self.embedding,
            {
                "backend": type(self.embedding).__qualname__,
                "model_name": self.embedding.model_name,
            },
        )
        index_fingerprint = backend_fingerprint(
            self.index,
            {"backend": type(self.index).__qualname__},
        )
        identity = {
            "schema_version": "rag-index-generation-0.1",
            "collection_id": self.collection.manifest.collection_id,
            "collection_manifest_sha256": self.collection.manifest_sha256,
            "embedding_fingerprint": embedding_fingerprint,
            "index_fingerprint": index_fingerprint,
            "dense_dimension": dense_dimension,
            "chunk_count": len(self.collection.chunks),
        }
        generation_id = f"index_{configuration_sha256(identity)[:24]}"
        return IndexGeneration(
            index_generation_id=generation_id,
            **identity,
        )


def _validate_vector_matrix(
    vectors: Sequence[Sequence[float]],
    expected_count: int,
) -> int:
    """校验向量数量、维度和数值类型，并返回统一维度。"""

    if len(vectors) != expected_count:
        raise ValueError("embedding output count does not match collection")
    dimensions = {len(vector) for vector in vectors}
    if not dimensions or len(dimensions) != 1 or 0 in dimensions:
        raise ValueError("embedding output must have one non-zero dimension")
    if any(not isinstance(value, (int, float)) for vector in vectors for value in vector):
        raise ValueError("embedding output must contain numeric values")
    return dimensions.pop()


def _declared_embedding_dimension(embedding: EmbeddingProvider) -> int | None:
    """读取后端可选的已知维度，使完整代次可在编码前复用。"""

    dimension = getattr(embedding, "dimension", None)
    if dimension is None:
        dimension = getattr(embedding, "dimensions", None)
    if dimension is None:
        return None
    if not isinstance(dimension, int) or dimension <= 0:
        raise ValueError("declared embedding dimension must be a positive integer")
    return dimension
