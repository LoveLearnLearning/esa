# backend/agent/rag/tests/test_agent_api.py

"""

这个文件干什么：ESA Agent 与正式 RetrievalService 之间的接口回归测试。

直白点说就是：用假的检索服务检查 Agent 看到的返回格式、阈值行为和报错信息一直保持兼容。

ESA Agent 与正式 RetrievalService 之间的接口回归测试。
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import cast

import pytest

from backend.agent.rag.agent_api import (
    B1_TOP_LEVEL_KEYS,
    B2_RESULT_KEYS,
    B2_TOP_LEVEL_KEYS,
    configure_retrieval_service,
    get_retrieval_service,
    knowledge_base_stats,
    reset_retrieval_service,
    retrieve_knowledge_payload,
)
from backend.agent.rag.retrieval.contracts import (
    ContextLevel,
    Evidence,
    RetrievalConfig,
    SearchHit,
    SearchResponse,
    SearchTrace,
)
from backend.agent.rag.retrieval.service import RetrievalService


class _FakeService:
    """只提供 Agent 适配层使用的 RetrievalService 表面。"""

    def __init__(self, response: SearchResponse) -> None:
        self.response = response
        self.collection = SimpleNamespace(
            manifest=SimpleNamespace(collection_id="collection_test"),
            documents=(object(),),
            chunks=(object(),),
        )
        self.embedding = SimpleNamespace(model_name="embedding-test")
        self.reranker = SimpleNamespace(model_name="reranker-test")
        self.index = SimpleNamespace()
        self.config = RetrievalConfig()

    def search(self, query: str) -> SearchResponse:
        assert query == self.response.query
        return self.response


@pytest.fixture(autouse=True)
def _reset_service() -> Iterator[None]:
    reset_retrieval_service()
    yield
    reset_retrieval_service()


def _response(
    rerank_score: float | None = 0.875,
    locators: tuple[dict[str, object], ...] | None = None,
) -> SearchResponse:
    evidence = Evidence(
        evidence_id="evidence_1",
        chunk_id="chunk_1",
        element_id="element_1",
        text_layer_id="text_1",
        text_start=0,
        text_end=4,
        evidence_text="测试证据",
        text_origin="native",
        quote_eligible=True,
        derivation="primary_text_span",
        quality_issue_ids=(),
        document_id="document_1",
        source_version_id="source_1",
        parse_revision_id="parse_1",
        document_name="测试文档.pdf",
        section_path=("第一章",),
        locators=locators if locators is not None else (
            {
                "locator_id": "locator_1",
                "kind": "page",
                "container_id": "page_1",
                "container_index": 0,
            },
        ),
        asset_ids=(),
    )
    hit = SearchHit(
        chunk_id="chunk_1",
        rrf_score=0.031,
        rerank_score=rerank_score,
        evidence=(evidence,),
        context_chunk_ids=("chunk_1",),
        context_text="测试上下文",
    )
    return SearchResponse(
        query="什么是测试？",
        context_level=ContextLevel.EVIDENCE,
        hits=(hit,),
        trace=SearchTrace(
            rankings={"rrf": ("chunk_1",), "reranker": ("chunk_1",)},
            degraded=(),
        ),
    )


def _configure(response: SearchResponse) -> None:
    service = cast(RetrievalService, _FakeService(response))
    configure_retrieval_service(service)


def test_retrieve_knowledge_preserves_old_shape_and_adds_evidence() -> None:
    _configure(_response())

    payload = retrieve_knowledge_payload("什么是测试？", top_k=1)

    assert tuple(payload) == B2_TOP_LEVEL_KEYS
    assert payload["result_count"] == 1
    assert payload["context_text"] == "测试上下文"
    assert payload["sources"] == ["【来源 1】测试文档.pdf · 第一章 · 第1页"]
    result = payload["results"][0]
    assert tuple(result) == B2_RESULT_KEYS
    assert result["source"] == "测试文档.pdf"
    assert result["score_type"] == "reranker"
    assert result["evidence"][0]["element_id"] == "element_1"


def test_group_locator_and_missing_locator_do_not_assume_page() -> None:
    _configure(
        _response(
            locators=(
                {
                    "locator_id": "group_1",
                    "kind": "group",
                    "container_id": "group_000001",
                    "container_index": 1,
                    "metadata": {"source_format": "pptx"},
                },
            )
        )
    )
    grouped = retrieve_knowledge_payload("什么是测试？", top_k=1)
    assert grouped["results"][0]["page"] is None
    assert grouped["sources"] == [
        "【来源 1】测试文档.pdf · 第一章 · PPTX 解析组 2"
    ]

    _configure(_response(locators=()))
    unlocated = retrieve_knowledge_payload("什么是测试？", top_k=1)
    assert unlocated["results"][0]["page"] is None
    assert unlocated["sources"] == ["【来源 1】测试文档.pdf · 第一章"]


def test_similarity_threshold_requires_reranker_probability() -> None:
    _configure(_response(rerank_score=None))

    with pytest.raises(RuntimeError, match="requires an active reranker"):
        retrieve_knowledge_payload("什么是测试？", similarity_threshold=0.5)


def test_unconfigured_service_has_clear_error() -> None:
    with pytest.raises(RuntimeError, match="not configured"):
        get_retrieval_service()


def test_knowledge_base_stats_uses_injected_service() -> None:
    _configure(_response())

    stats = knowledge_base_stats()

    assert tuple(stats) == B1_TOP_LEVEL_KEYS
    assert tuple(stats["config"]) == (
        "dense_limit",
        "bm25_body_limit",
        "bm25_heading_limit",
        "rrf_limit",
        "rerank_limit",
        "reranker_batch_size",
        "final_limit",
        "rrf_k",
        "section_window",
        "max_context_tokens",
        "rerank_threshold",
        "fusion_method",
        "dense_weight",
        "lexical_body_weight",
        "lexical_gate_enabled",
        "reranker_enabled",
        "reranker_prior_weight",
    )
    assert stats["collection_id"] == "collection_test"
    assert stats["total_chunks"] == 1
    assert stats["embedding_model"] == "embedding-test"
