# backend/agent/rag/tests/test_retrieval.py

"""

这个文件干什么：正式 ChunkCollection 检索链的无模型、无 Qdrant 回归测试。

直白点说就是：不用真实模型和 Qdrant 也把正式检索链跑一遍，防止三路召回、降级、证据和安全校验回归。

正式 ChunkCollection 检索链的无模型、无 Qdrant 回归测试。
"""

from __future__ import annotations

import json
import shutil
from argparse import Namespace
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

import pytest

from backend.agent.DocIR import load_document
from backend.agent.rag import (
    ContextLevel,
    HashingEmbeddingProvider,
    IndexingService,
    LexicalOverlapReranker,
    ReferenceIndex,
    RetrievalConfig,
    RetrievalService,
    TransformersEmbeddingProvider,
    TransformersReranker,
    load_chunk_collection,
)
from backend.agent.rag.cli import index as qdrant_lifecycle
from backend.agent.rag.collection import LoadedChunkCollection
from backend.agent.rag.evaluation import EvaluationCase, evaluate_layers
from backend.agent.rag.evaluation.benchmark import benchmark_backend
from backend.agent.rag.evaluation.reference import (
    load_evaluation_cases,
    run_reference_evaluation,
)
from backend.agent.rag.indexes import (
    CollectionNotFound,
    IndexGenerationConflict,
    QdrantIndex,
)
from backend.agent.rag.indexing import IndexDeployment, load_deployment, save_deployment
from backend.agent.rag.inference import InferenceUnavailable
from backend.agent.rag.paths import WORKSPACE_ROOT
from backend.agent.rag.retrieval.contracts import RankedItem
from backend.agent.rag.retrieval.fusion import reciprocal_rank_fusion

MANIFEST = (
    WORKSPACE_ROOT
    / "artifacts/chunk/collections/collection_bc7a6054e159eb7346e94df0/manifest.json"
)
CASES = WORKSPACE_ROOT / "data/evaluation/reference_evaluation_v1.json"


@pytest.fixture(scope="module")
def collection() -> LoadedChunkCollection:
    """处理 `collection` 相关逻辑。"""
    if not MANIFEST.exists():
        pytest.skip("ESA checkout does not include the external real-corpus artifacts")
    try:
        return load_chunk_collection(MANIFEST)
    except ValueError as exc:
        pytest.skip(
            f"external chunk artifacts predate the current DocIR contract: {exc}"
        )


@pytest.fixture(scope="module")
def service(collection: LoadedChunkCollection) -> RetrievalService:
    """处理 `service` 相关逻辑。"""
    index = ReferenceIndex()
    embedding = HashingEmbeddingProvider()
    IndexingService(collection, index, embedding).build()
    return RetrievalService(
        collection,
        index,
        embedding,
        LexicalOverlapReranker(),
        RetrievalConfig(final_limit=5),
    )


def _copy_collection(tmp_path: Path) -> Path:
    """处理 `_copy_collection` 相关逻辑。"""
    if not MANIFEST.exists():
        pytest.skip("ESA checkout does not include the external real-corpus artifacts")
    target = tmp_path / "collection"
    shutil.copytree(MANIFEST.parent, target)
    return target / "manifest.json"


def test_load_real_collection_counts(collection: LoadedChunkCollection) -> None:
    """验证 `load_real_collection_counts` 场景。"""
    assert len(collection.documents) == 7
    assert len(collection.chunks) == 532
    assert sum(len(chunk.evidence) for chunk in collection.chunks) == 2165


def test_real_evidence_keeps_ocr_risk_and_multi_locator(
    collection: LoadedChunkCollection,
) -> None:
    """验证 `real_evidence_keeps_ocr_risk_and_multi_locator` 场景。"""
    evidence = [item for chunk in collection.chunks for item in chunk.evidence]
    assert all(not item.quote_eligible for item in evidence)
    assert all(
        item.text_origin.value == "native_or_ocr_unverified" for item in evidence
    )
    assert sum(len(item.locators) > 1 for item in evidence) == 138
    assert sum(bool(item.asset_ids) for item in evidence) == 195


def test_all_real_evidence_references_resolve_to_docir(
    collection: LoadedChunkCollection,
) -> None:
    """验证 `all_real_evidence_references_resolve_to_docir` 场景。"""
    docir_paths = (WORKSPACE_ROOT / "artifacts/docir/runs/full-corpus-20260802").glob(
        "*/document.json"
    )
    documents = {
        document.document_id: document for document in map(load_document, docir_paths)
    }
    assert set(documents) == set(collection.document_names)
    for chunk in collection.chunks:
        document = documents[chunk.document_id]
        elements = {element.element_id: element for element in document.elements}
        assets = {asset.asset_id for asset in document.assets}
        issues = {issue.issue_id for issue in document.quality_issues}
        for evidence in chunk.evidence:
            assert evidence.element_id in elements
            element = elements[evidence.element_id]
            assert {item.locator_id for item in evidence.locators} <= {
                locator.locator_id for locator in element.locators
            }
            assert set(evidence.asset_ids) <= assets
            assert set(evidence.quality_issue_ids) <= issues | {
                "chunk_ocr_risk_unverified_origin"
            }
            if evidence.text_layer_id is not None:
                layers = {layer.text_layer_id: layer for layer in element.text.layers}
                assert evidence.text_layer_id in layers
                if evidence.text_start is not None:
                    layer = layers[evidence.text_layer_id]
                    assert (
                        layer.text[evidence.text_start : evidence.text_end]
                        == evidence.text
                    )


def test_three_routes_are_visible(service: RetrievalService) -> None:
    """验证 `three_routes_are_visible` 场景。"""
    response = service.search("什么是黑盒测试？")
    assert set(response.trace.rankings) == {
        "dense",
        "bm25_body",
        "bm25_heading",
        "fusion",
        "final",
    }
    assert response.hits


def test_context_never_crosses_document_or_section(
    collection: LoadedChunkCollection, service: RetrievalService
) -> None:
    """验证 `context_never_crosses_document_or_section` 场景。"""
    hit = service.search("黑盒测试", ContextLevel.FULL_READ).hits[0]
    by_id = {chunk.chunk_id: chunk for chunk in collection.chunks}
    identities = {
        (by_id[chunk_id].document_id, by_id[chunk_id].section_id)
        for chunk_id in hit.context_chunk_ids
    }
    assert len(identities) == 1


def test_response_evidence_is_lossless_reference(service: RetrievalService) -> None:
    """验证 `response_evidence_is_lossless_reference` 场景。"""
    evidence = service.search("黑盒测试").hits[0].evidence[0]
    assert evidence.evidence_text
    assert evidence.locators
    assert evidence.text_origin == "native_or_ocr_unverified"
    assert evidence.quote_eligible is False


def test_rrf_is_rank_only_and_reproducible() -> None:
    """验证 `rrf_is_rank_only_and_reproducible` 场景。"""
    routes = {
        "dense": [RankedItem("b", 99), RankedItem("a", 1)],
        "body": [RankedItem("a", 0.01), RankedItem("b", 0.001)],
    }
    first = reciprocal_rank_fusion(routes, rrf_k=60)
    second = reciprocal_rank_fusion(dict(reversed(list(routes.items()))), rrf_k=60)
    assert first == second
    assert [item.chunk_id for item in first] == ["a", "b"]


def test_reference_embedding_is_deterministic_and_normalized() -> None:
    """验证 `reference_embedding_is_deterministic_and_normalized` 场景。"""
    provider = HashingEmbeddingProvider()
    first = provider.embed(["黑盒测试 black box"])[0]
    second = provider.embed(["黑盒测试 black box"])[0]
    assert first == second and len(first) == 384
    assert sum(value * value for value in first) == pytest.approx(1.0)


def test_reference_reranker_prefers_overlap() -> None:
    """验证 `reference_reranker_prefers_overlap` 场景。"""
    scores = LexicalOverlapReranker().score(
        "黑盒测试", ["黑盒测试不关注内部结构", "完全无关的薪资信息"]
    )
    assert scores[0] > scores[1]


def test_transformers_reranker_instruction_allows_cross_language_relevance() -> None:
    """Reranker instruction must not require query/document language matching."""
    instruction = TransformersReranker().instruction.lower()
    assert "different languages" in instruction
    assert "cross-lingual semantic relevance" in instruction
    assert "lexical or language matching" in instruction


def test_collection_loader_rejects_document_hash_tamper(tmp_path: Path) -> None:
    """验证 `collection_loader_rejects_document_hash_tamper` 场景。"""
    manifest_path = _copy_collection(tmp_path)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    document_path = manifest_path.parent / raw["documents"][0]["path"]
    document_path.write_bytes(document_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="SHA-256"):
        load_chunk_collection(manifest_path)


def test_collection_loader_rejects_missing_document(tmp_path: Path) -> None:
    """验证 `collection_loader_rejects_missing_document` 场景。"""
    manifest_path = _copy_collection(tmp_path)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    (manifest_path.parent / raw["documents"][0]["path"]).unlink()
    with pytest.raises(FileNotFoundError):
        load_chunk_collection(manifest_path)


def test_collection_loader_rejects_unsafe_path(tmp_path: Path) -> None:
    """验证 `collection_loader_rejects_unsafe_path` 场景。"""
    manifest_path = _copy_collection(tmp_path)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["documents"][0]["path"] = "../outside.json"
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="安全相对路径"):
        load_chunk_collection(manifest_path)


def test_evaluation_case_enforces_positive_and_negative_gold() -> None:
    """验证 `evaluation_case_enforces_positive_and_negative_gold` 场景。"""
    with pytest.raises(ValueError, match="need document"):
        EvaluationCase(
            "p", "q", True, frozenset(), frozenset(), frozenset(), ("body",), "note"
        )
    negative = EvaluationCase(
        "n",
        "q",
        False,
        frozenset(),
        frozenset(),
        frozenset(),
        ("unanswerable",),
        "note",
    )
    assert not negative.answerable


def test_layer_evaluation_reports_unanswerable_false_positives() -> None:
    """Every layer must expose acceptance and abstention behavior on negatives."""
    positive = EvaluationCase(
        "p",
        "q",
        True,
        frozenset({"a"}),
        frozenset({"e"}),
        frozenset({"d"}),
        ("body",),
        "note",
    )
    negative = EvaluationCase(
        "n",
        "x",
        False,
        frozenset(),
        frozenset(),
        frozenset(),
        ("unanswerable",),
        "note",
    )
    layers = {
        name: ["a"]
        for name in (
            "dense",
            "bm25_body",
            "bm25_heading",
            "fusion",
            "reranker",
            "final",
        )
    }
    metrics = evaluate_layers([positive, negative], lambda _query: layers)
    assert all(
        value.query_count == 2
        and value.answerable_query_count == 1
        and value.unanswerable_query_count == 1
        and value.hit_at_5 == 1.0
        and value.answerable_acceptance_rate == 1.0
        and value.unanswerable_abstention_rate == 0.0
        and value.unanswerable_false_positive_rate == 1.0
        and value.answerability_accuracy == 0.5
        for value in metrics.values()
    )


def test_layer_evaluation_counts_empty_negative_ranking_as_abstention() -> None:
    positive = EvaluationCase(
        "p",
        "q",
        True,
        frozenset({"a"}),
        frozenset({"e"}),
        frozenset({"d"}),
        ("body",),
        "note",
    )
    negative = EvaluationCase(
        "n",
        "x",
        False,
        frozenset(),
        frozenset(),
        frozenset(),
        ("unanswerable",),
        "note",
    )
    layer_names = ("dense", "bm25_body", "bm25_heading", "fusion", "reranker", "final")

    metrics = evaluate_layers(
        [positive, negative],
        lambda query: {name: (["a"] if query == "q" else []) for name in layer_names},
    )

    assert all(value.unanswerable_abstention_rate == 1.0 for value in metrics.values())
    assert all(
        value.unanswerable_false_positive_rate == 0.0 for value in metrics.values()
    )
    assert all(value.answerability_accuracy == 1.0 for value in metrics.values())


class CapturingQdrant(QdrantIndex):
    """封装 `CapturingQdrant` 的状态与行为。"""

    calls: ClassVar[list[tuple[str, str, dict[str, Any] | None]]] = []

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """处理 `_request` 相关逻辑。"""
        self.calls.append((method, path, payload))
        if path.endswith("/points/query"):
            return {"result": {"points": []}}
        return {"status": "ok"}


def test_qdrant_ingest_uses_formal_chunk_and_fixed_bm25(
    collection: LoadedChunkCollection,
) -> None:
    """验证 `qdrant_ingest_uses_formal_chunk_and_fixed_bm25` 场景。"""
    CapturingQdrant.calls.clear()
    index = CapturingQdrant("http://127.0.0.1:6333", "formal")
    index.build(
        collection.chunks[:1],
        [[1.0, 0.0]],
        generation_id="index_test",
    )
    point = CapturingQdrant.calls[-1][2]["points"][0]
    assert point["payload"]["chunk_revision_id"]
    assert point["payload"]["index_generation_id"] == "index_test"
    assert point["vector"]["bm25_body"]["options"] == {
        "tokenizer": "multilingual",
        "language": "none",
    }


def test_online_failures_degrade_to_bm25_and_rrf(
    collection: LoadedChunkCollection,
) -> None:
    """验证 `online_failures_degrade_to_bm25_and_rrf` 场景。"""

    class FailingEmbedding(HashingEmbeddingProvider):
        """封装 `FailingEmbedding` 的状态与行为。"""

        def embed_query(self, query: str) -> list[float]:
            """处理 `embed_query` 相关逻辑。"""
            raise InferenceUnavailable("offline")

    class FailingReranker(LexicalOverlapReranker):
        """封装 `FailingReranker` 的状态与行为。"""

        def score(self, query: str, documents: Sequence[str]) -> list[float]:
            """处理 `score` 相关逻辑。

            Args:
                query: str => 查询文本。
                documents: Sequence[str] => `documents` 参数。

            Returns:
                list[float] => 处理结果。
            """
            raise InferenceUnavailable("offline")

    index = ReferenceIndex()
    build_embedding = HashingEmbeddingProvider()
    IndexingService(collection, index, build_embedding).build()
    service = RetrievalService(
        collection,
        index,
        FailingEmbedding(),
        FailingReranker(),
        RetrievalConfig(reranker_enabled=True),
    )
    response = service.search("反向传播")
    assert response.trace.rankings["dense"] == ()
    assert "reranker" not in response.trace.rankings
    assert response.trace.rankings["final"]
    assert response.trace.fusion["applied_method"] == "lexical_rrf_fallback"
    assert response.trace.fusion["dense_weight"] == 0.0
    assert response.trace.fusion["bm25_body_weight"] == 1.0
    assert response.trace.fusion["bm25_heading_weight"] == 1.0
    assert {item.split(":", 1)[0] for item in response.trace.degraded} == {
        "dense_unavailable",
        "reranker_unavailable",
    }


def test_benchmark_remains_backend_neutral() -> None:
    """验证 `benchmark_remains_backend_neutral` 场景。"""
    result = benchmark_backend(
        "fake",
        lambda: object(),
        lambda _backend, values: list(values),
        ["a", "b"],
        iterations=2,
    )
    assert result.items_per_second > 0


def test_blank_query_is_rejected(service: RetrievalService) -> None:
    """验证 `blank_query_is_rejected` 场景。"""
    with pytest.raises(ValueError, match="blank"):
        service.search("   ")


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("dense_limit", 0),
        ("bm25_body_limit", 0),
        ("bm25_heading_limit", 0),
        ("rrf_limit", 0),
        ("rerank_limit", 0),
        ("final_limit", 0),
        ("rrf_k", 0),
    ],
)
def test_retrieval_config_reports_the_invalid_field(
    field_name: str,
    value: int,
) -> None:
    """验证 `retrieval_config_reports_the_invalid_field` 场景。"""
    with pytest.raises(ValueError, match=field_name):
        RetrievalConfig(**{field_name: value})


def test_index_generation_inputs_are_stable(
    collection: LoadedChunkCollection,
) -> None:
    """验证 `index_generation_inputs_are_stable` 场景。"""
    embedding = HashingEmbeddingProvider()
    assert len(collection.manifest_sha256) == 64
    assert (
        embedding.configuration_fingerprint
        == HashingEmbeddingProvider().configuration_fingerprint
    )


def test_indexing_service_does_not_rebuild_same_instance(
    collection: LoadedChunkCollection,
) -> None:
    """验证 `indexing_service_does_not_rebuild_same_instance` 场景。"""

    class CountingIndex(ReferenceIndex):
        """封装 `CountingIndex` 的状态与行为。"""

        build_count = 0

        def build(
            self,
            chunks: Sequence[Any],
            dense_vectors: Sequence[Sequence[float]],
            *,
            generation_id: str,
        ) -> None:
            """构建 `build` 相关数据。

            Args:
                chunks: Sequence[Any] => `chunks` 参数。
                dense_vectors: Sequence[Sequence[float]] => `dense_vectors` 参数。
                generation_id: str => generation ID。
            """
            self.build_count += 1
            super().build(
                chunks,
                dense_vectors,
                generation_id=generation_id,
            )

    index = CountingIndex()
    indexing = IndexingService(collection, index, HashingEmbeddingProvider())
    first = indexing.build()
    second = indexing.build()

    assert first.indexed is True
    assert second.indexed is False
    assert first.generation == second.generation
    assert first.generation.chunk_count == len(collection.chunks)
    assert index.build_count == 1


class StatefulQdrant(QdrantIndex):
    """只模拟生命周期 REST 语义，不模拟相似度查询。"""

    def __post_init__(self) -> None:
        """完成实例初始化后的校验与派生字段构建。"""
        super().__post_init__()
        object.__setattr__(self, "exists", False)
        object.__setattr__(self, "dense_dimension", None)
        object.__setattr__(self, "points", {})
        object.__setattr__(self, "upsert_calls", 0)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """处理 `_request` 相关逻辑。"""
        if method == "GET":
            if not self.exists:
                raise CollectionNotFound("missing")
            return {
                "result": {
                    "config": {
                        "params": {
                            "vectors": {
                                self.dense_name: {
                                    "size": self.dense_dimension,
                                    "distance": "Cosine",
                                }
                            },
                            "sparse_vectors": {
                                self.body_name: {},
                                self.heading_name: {},
                            },
                        }
                    }
                }
            }
        if method == "PUT" and path.endswith(self.collection):
            object.__setattr__(self, "exists", True)
            object.__setattr__(
                self,
                "dense_dimension",
                payload["vectors"][self.dense_name]["size"],
            )
            return {"status": "ok"}
        if method == "PUT" and "/points" in path:
            object.__setattr__(self, "upsert_calls", self.upsert_calls + 1)
            for point in payload["points"]:
                self.points[point["id"]] = point
            return {"status": "ok"}
        if method == "POST" and path.endswith("/points/count"):
            generation_id = None
            if payload and "filter" in payload:
                generation_id = payload["filter"]["must"][0]["match"]["value"]
            points = self.points.values()
            if generation_id is not None:
                points = (
                    point
                    for point in points
                    if point["payload"].get("index_generation_id") == generation_id
                )
            return {"result": {"count": sum(1 for _point in points)}}
        raise AssertionError(f"unexpected request: {method} {path}")


def test_qdrant_lifecycle_reuses_complete_generation_across_services(
    collection: LoadedChunkCollection,
) -> None:
    """验证 `qdrant_lifecycle_reuses_complete_generation_across_services` 场景。"""

    class CountingEmbedding:
        """封装 `CountingEmbedding` 的状态与行为。"""

        model_name = "counting-reference-embedding"
        dimensions = 384

        def __init__(self) -> None:
            """初始化 `CountingEmbedding` 实例。"""
            self.calls = 0
            self.delegate = HashingEmbeddingProvider(
                dimensions=self.dimensions,
                model_name=self.model_name,
            )

        @property
        def configuration_fingerprint(self) -> str:
            """处理 `configuration_fingerprint` 相关逻辑。"""
            return self.delegate.configuration_fingerprint

        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            """处理 `embed` 相关逻辑。"""
            return self.delegate.embed(texts)

        def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
            """处理 `embed_documents` 相关逻辑。"""
            self.calls += 1
            return self.delegate.embed_documents(texts)

    index = StatefulQdrant("http://127.0.0.1:6333", "generation_test")
    embedding = CountingEmbedding()

    first = IndexingService(collection, index, embedding).build()
    upserts_after_first = index.upsert_calls
    second = IndexingService(collection, index, embedding).build()

    assert first.indexed is True
    assert second.indexed is False
    assert first.generation == second.generation
    assert len(index.points) == len(collection.chunks)
    assert index.upsert_calls == upserts_after_first
    assert embedding.calls == 1


def test_qdrant_lifecycle_rejects_mixed_generations(
    collection: LoadedChunkCollection,
) -> None:
    """验证 `qdrant_lifecycle_rejects_mixed_generations` 场景。"""
    index = StatefulQdrant("http://127.0.0.1:6333", "generation_conflict")
    object.__setattr__(index, "exists", True)
    object.__setattr__(index, "dense_dimension", 384)
    index.points["old"] = {"payload": {"index_generation_id": "index_old"}}

    with pytest.raises(IndexGenerationConflict, match="another index generation"):
        IndexingService(collection, index, HashingEmbeddingProvider()).build()


def test_qdrant_validate_existing_does_not_create_missing_collection() -> None:
    """验证 `qdrant_validate_existing_does_not_create_missing_collection` 场景。"""
    index = StatefulQdrant("http://127.0.0.1:6333", "missing")

    with pytest.raises(CollectionNotFound):
        index.validate_existing(384, "index_missing", 1)

    assert index.exists is False


def test_index_deployment_round_trip_and_identity_guard(
    collection: LoadedChunkCollection,
    tmp_path: Path,
) -> None:
    """验证 `index_deployment_round_trip_and_identity_guard` 场景。"""
    result = IndexingService(
        collection,
        ReferenceIndex(),
        HashingEmbeddingProvider(),
    ).build()
    deployment = IndexDeployment.create(
        result.generation,
        qdrant_base_url="http://127.0.0.1:6333/",
        qdrant_collection="formal_generation",
        embedding_backend="reference",
        embedding_model_name="reference-hashing-embedding-0.1",
        embedding_base_url=None,
    )
    path = tmp_path / "deployment.json"
    save_deployment(deployment, path)

    assert load_deployment(path) == deployment
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["qdrant_collection"] = "tampered"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="deployment_id"):
        load_deployment(path)


def test_transformers_embedding_uses_bounded_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 `transformers_embedding_uses_bounded_batches` 场景。"""
    provider = TransformersEmbeddingProvider(
        model_name="/models/embedding", batch_size=2
    )
    batches: list[list[str]] = []
    monkeypatch.setattr(provider, "_load", lambda: None)

    def embed_batch(texts: Sequence[str]) -> list[list[float]]:
        """处理 `embed_batch` 相关逻辑。"""
        batches.append(list(texts))
        return [[float(len(text))] for text in texts]

    monkeypatch.setattr(provider, "_embed_batch", embed_batch)

    assert provider.embed(["a", "bb", "ccc"]) == [[1.0], [2.0], [3.0]]
    assert batches == [["a", "bb"], ["ccc"]]


def test_transformers_embedding_runtime_device_does_not_change_index_identity() -> None:
    """验证 `transformers_embedding_runtime_device_does_not_change_index_identity` 场景。"""
    default = TransformersEmbeddingProvider(device="cuda")
    remapped = TransformersEmbeddingProvider(
        device="cuda",
        runtime_device="cuda:4",
    )

    assert remapped.configuration_fingerprint == default.configuration_fingerprint


def test_transformers_embedding_rejects_invalid_batch_size() -> None:
    """验证 `transformers_embedding_rejects_invalid_batch_size` 场景。"""
    with pytest.raises(ValueError, match="batch_size must be positive"):
        TransformersEmbeddingProvider(batch_size=0)


def test_transformers_embedding_rejects_invalid_dimension() -> None:
    """验证 `transformers_embedding_rejects_invalid_dimension` 场景。"""
    with pytest.raises(ValueError, match="dimension must be positive"):
        TransformersEmbeddingProvider(dimension=0)


def test_lifecycle_selects_local_transformers_backend() -> None:
    """验证 `lifecycle_selects_local_transformers_backend` 场景。"""
    provider = qdrant_lifecycle._embedding_provider(
        "transformers",
        "/models/Qwen3-Embedding-4B",
        None,
        2560,
    )

    assert isinstance(provider, TransformersEmbeddingProvider)
    assert provider.model_name == "/models/Qwen3-Embedding-4B"


def test_lifecycle_selects_optional_local_reranker() -> None:
    """验证 `lifecycle_selects_optional_local_reranker` 场景。"""
    disabled = qdrant_lifecycle._reranker(
        "none",
        "/models/Qwen3-Reranker-4B",
        None,
    )
    enabled = qdrant_lifecycle._reranker(
        "transformers",
        "/models/Qwen3-Reranker-4B",
        None,
    )

    assert disabled is None
    assert isinstance(enabled, TransformersReranker)
    assert enabled.model_name == "/models/Qwen3-Reranker-4B"


def test_build_deployment_creates_its_output_directory(
    collection: LoadedChunkCollection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 `build_deployment_creates_its_output_directory` 场景。"""
    embedding = HashingEmbeddingProvider()
    index = ReferenceIndex()
    monkeypatch.setattr(
        qdrant_lifecycle, "load_chunk_collection", lambda _path: collection
    )
    monkeypatch.setattr(
        qdrant_lifecycle,
        "_embedding_provider",
        lambda *_arguments: embedding,
    )
    monkeypatch.setattr(qdrant_lifecycle, "_qdrant_index", lambda *_arguments: index)
    arguments = Namespace(
        manifest=MANIFEST,
        output=tmp_path / "indexes",
        qdrant_url="http://127.0.0.1:6333",
        collection="formal_generation",
        embedding_backend="reference",
        embedding_model=embedding.model_name,
        embedding_url=None,
        embedding_dimension=384,
    )

    manifest_path = qdrant_lifecycle.build_deployment(arguments)

    assert manifest_path.is_file()
    assert load_deployment(manifest_path).qdrant_collection == "formal_generation"


def test_real_evaluation_set_resolves_all_gold(
    collection: LoadedChunkCollection,
) -> None:
    """验证 `real_evaluation_set_resolves_all_gold` 场景。"""
    cases = load_evaluation_cases(CASES, collection)
    assert len(cases) == 42
    assert sum(case.answerable for case in cases) == 35


def test_reference_evaluation_is_byte_deterministic(tmp_path: Path) -> None:
    """验证 `reference_evaluation_is_byte_deterministic` 场景。"""
    if not MANIFEST.exists() or not CASES.exists():
        pytest.skip("ESA checkout does not include the external evaluation artifacts")
    first_root, first_summary = run_reference_evaluation(MANIFEST, CASES, tmp_path)
    before = {
        path.name: path.read_bytes() for path in first_root.iterdir() if path.is_file()
    }
    second_root, second_summary = run_reference_evaluation(MANIFEST, CASES, tmp_path)
    after = {
        path.name: path.read_bytes() for path in second_root.iterdir() if path.is_file()
    }
    assert first_root == second_root
    assert first_summary == second_summary
    assert before == after


def test_reference_results_never_claim_quote_eligibility(tmp_path: Path) -> None:
    """验证 `reference_results_never_claim_quote_eligibility` 场景。"""
    if not MANIFEST.exists() or not CASES.exists():
        pytest.skip("ESA checkout does not include the external evaluation artifacts")
    root, _summary = run_reference_evaluation(MANIFEST, CASES, tmp_path)
    raw = json.loads((root / "results.json").read_text(encoding="utf-8"))
    assert all(
        hit["quote_eligible_count"] == 0
        for case in raw["cases"]
        for hit in case["hits"]
    )
