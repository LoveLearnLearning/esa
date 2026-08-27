"""Unit tests for the production retrieval context router."""

from backend.agent.rag.context_routing import (
    MetadataProfile,
    RetrievalRouteInput,
    RuleBasedContextRouter,
)


def _profile(query: str) -> MetadataProfile:
    return RuleBasedContextRouter().route(
        RetrievalRouteInput(current_user_message=query)
    ).profile


def test_rule_router_covers_bootstrap_profiles() -> None:
    assert _profile("解释黑盒测试和白盒测试的区别") is MetadataProfile.MINIMAL
    assert _profile("这个结论的出处是什么？") is MetadataProfile.SOURCE
    assert _profile("它来自哪本书？") is MetadataProfile.SOURCE
    assert _profile("这段内容在第几页？") is MetadataProfile.LOCATION
    assert _profile("给我 chunk_id、retrieval_score 和完整 metadata") is MetadataProfile.FULL
    assert _profile("机器学习里的 F1 score 是什么？") is MetadataProfile.MINIMAL


def test_explicit_negation_suppresses_only_the_negated_request() -> None:
    assert _profile("不用给我出处，直接解释") is MetadataProfile.MINIMAL
    assert _profile("不要引用，概括一下") is MetadataProfile.MINIMAL
    assert _profile("无需页码，告诉我来源") is MetadataProfile.SOURCE
    assert _profile("不要 metadata，只总结") is MetadataProfile.MINIMAL


def test_route_decision_is_auditable() -> None:
    decision = RuleBasedContextRouter().route(
        RetrievalRouteInput(current_user_message="这个结论来自哪篇论文？")
    )
    assert decision.router_type == "rule"
    assert decision.router_version == "metadata_projection.rule.v1"
    assert decision.reason_code == "explicit_source"
    assert decision.matched_rule == "哪篇论文"
