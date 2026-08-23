# backend/agent/rag/tests/test_agent_api.py

"""

这个文件干什么：ESA Agent 与正式 RetrievalService 之间的接口回归测试。

直白点说就是：用假的检索服务检查 Agent 看到的返回格式、阈值行为和报错信息一直保持兼容。

ESA Agent 与正式 RetrievalService 之间的接口回归测试。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from types import SimpleNamespace
from typing import cast

import pytest

from backend.agent.rag.agent_api import (
    B1_TOP_LEVEL_KEYS,
    B2_CONTEXT_TOKEN_BUDGET,
    B2_RESULT_CONTEXT_TOKEN_LIMIT,
    B2_RESULT_KEYS,
    B2_TOP_LEVEL_KEYS,
    configure_retrieval_service,
    get_retrieval_service,
    knowledge_base_stats,
    reset_retrieval_service,
    retrieve_knowledge_payload,
    retrieve_knowledge_result,
)
from backend.agent.rag.retrieval.context import estimate_tokens
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
        """初始化 `_FakeService` 实例。"""
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
        """搜索 `search` 相关数据。"""
        assert query == self.response.query
        return self.response


@pytest.fixture(autouse=True)
def _reset_service() -> Iterator[None]:
    """处理 `_reset_service` 相关逻辑。"""
    reset_retrieval_service()
    yield
    reset_retrieval_service()


def _response(
    rerank_score: float | None = 0.875,
    locators: tuple[dict[str, object], ...] | None = None,
    document_name: str = "测试文档.pdf",
) -> SearchResponse:
    """处理 `_response` 相关逻辑。"""
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
        document_name=document_name,
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
        retrieval_score=0.031,
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
            rankings={
                "fusion": ("chunk_1",),
                "reranker": ("chunk_1",),
                "final": ("chunk_1",),
            },
            fusion={
                "configured_method": "dense",
                "applied_method": "dense",
                "ranking_method": "reranker",
            },
            reranker_applied=True,
            degraded=(),
        ),
    )


def _configure(response: SearchResponse) -> None:
    """处理 `_configure` 相关逻辑。"""
    service = cast(RetrievalService, _FakeService(response))
    configure_retrieval_service(service)


def test_retrieve_knowledge_preserves_old_shape_and_adds_evidence() -> None:
    """验证 `retrieve_knowledge_preserves_old_shape_and_adds_evidence` 场景。"""
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


def test_retrieve_knowledge_compacts_context_with_a_global_budget() -> None:
    """长 chunk 按结果公平裁剪，且不突破 Agent 工具的总预算。"""

    original = _response()
    base_hit = original.hits[0]
    long_context = "TCP先发送SYN。服务器再返回SYNACK。客户端最后确认。" * 200
    hits = tuple(
        replace(
            base_hit,
            chunk_id=f"chunk_{index}",
            context_chunk_ids=(f"chunk_{index}",),
            context_text=long_context,
        )
        for index in range(5)
    )
    _configure(replace(original, hits=hits))

    payload = retrieve_knowledge_payload("什么是测试？", top_k=5)
    contents = [result["content"] for result in payload["results"]]

    assert payload["result_count"] == 5
    assert all(content.endswith("…") for content in contents)
    assert all(
        estimate_tokens(content) <= B2_RESULT_CONTEXT_TOKEN_LIMIT
        for content in contents
    )
    assert estimate_tokens(payload["context_text"]) <= B2_CONTEXT_TOKEN_BUDGET
    assert payload["context_text"] == "\n\n".join(contents)


def test_group_locator_and_missing_locator_do_not_assume_page() -> None:
    """验证 `group_locator_and_missing_locator_do_not_assume_page` 场景。"""
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


def test_page_number_and_display_locator_use_one_canonical_label() -> None:
    """A parser-supplied page label cannot contradict the displayed page."""

    _configure(
        _response(
            locators=(
                {
                    "locator_id": "page_4",
                    "kind": "page",
                    "container_id": "page_000003",
                    "container_index": 3,
                    "label": "iv",
                },
            )
        )
    )

    legacy = retrieve_knowledge_payload("什么是测试？", top_k=1)
    assert legacy["results"][0]["page"] == 4
    assert legacy["results"][0]["location"]["label"] == "第4页"
    assert legacy["sources"] == ["【来源 1】测试文档.pdf · 第一章 · 第4页"]


def test_display_name_removes_known_download_and_author_noise() -> None:
    raw_name = (
        "数据结构与算法分析 C语言描述(原书第2版)典藏版 "
        "(马克·艾伦·维斯 Mark.Allen.Weiss) "
        "(z-library.sk, 1lib.sk, z-lib.sk)_origin.pdf"
    )
    _configure(_response(document_name=raw_name))

    legacy = retrieve_knowledge_payload("什么是测试？", top_k=1)
    result = retrieve_knowledge_result("什么是测试？", top_k=1)

    expected = "数据结构与算法分析 C语言描述(原书第2版)典藏版"
    assert legacy["results"][0]["source"] == expected
    assert expected in legacy["sources"][0]
    assert result.display_content["results"][0]["source"] == expected
    assert (
        result.audit_metadata["response"]["hits"][0]["evidence"][0]["document_name"]
        == raw_name
    )


def test_similarity_threshold_requires_reranker_probability() -> None:
    """验证 `similarity_threshold_requires_reranker_probability` 场景。"""
    _configure(_response(rerank_score=None))

    with pytest.raises(RuntimeError, match="requires an active reranker"):
        retrieve_knowledge_payload("什么是测试？", similarity_threshold=0.5)


def test_v2_separates_model_display_and_audit_with_final_json_budget() -> None:
    original = _response()
    long_context = "TCP先发送SYN。服务器返回SYNACK。客户端确认。" * 500
    hits = tuple(
        replace(
            original.hits[0],
            chunk_id=f"chunk_{index}",
            context_chunk_ids=(f"chunk_{index}",),
            context_text=long_context,
        )
        for index in range(5)
    )
    _configure(replace(original, hits=hits))

    counter = lambda text: len(text)
    result = retrieve_knowledge_result(
        "什么是测试？", top_k=5, token_counter=counter
    )

    serialized = __import__("json").dumps(result.model_content, ensure_ascii=False)
    assert counter(serialized) <= 2048
    assert result.model_content["contract_version"] == "retrieve_knowledge.v2"
    assert '"evidence":' not in serialized
    assert '"context_text":' not in serialized
    assert result.model_content["budget"]["truncated"] is True
    assert result.display_content["results"][0]["source"] == "测试文档.pdf"
    assert result.audit_metadata["response"]["hits"][0]["evidence"]


def test_unconfigured_service_has_clear_error() -> None:
    """验证 `unconfigured_service_has_clear_error` 场景。"""
    with pytest.raises(RuntimeError, match="not configured"):
        get_retrieval_service()


def test_knowledge_base_stats_uses_injected_service() -> None:
    """验证 `knowledge_base_stats_uses_injected_service` 场景。"""
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
