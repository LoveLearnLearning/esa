"""视觉补全契约、路由和无标签准入测试。"""

from __future__ import annotations

from backend.agent.DocIR import FigureElement, FormulaElement, TableElement
from backend.agent.mm import (
    VisualDecision,
    VisualEnrichmentCandidate,
    VisualEnrichmentRequest,
    VisualEvidence,
    VisualRisk,
    VisualRoute,
    VisualRouteDecision,
    route_visual_element,
    select_visual_candidate,
)


def _request(route: VisualRoute = VisualRoute.GENERIC_VLM) -> VisualEnrichmentRequest:
    return VisualEnrichmentRequest(
        document_id="doc",
        element_id="figure",
        asset_id="asset",
        asset_sha256="a" * 64,
        media_type="image/png",
        asset_path="assets/figure.png",
        route=route,
        risk=VisualRisk.UNKNOWN,
    )


def test_route_skips_existing_machine_readable_content() -> None:
    table = TableElement(element_id="table", document_order=0, html="<table />")
    formula = FormulaElement(element_id="formula", document_order=1, latex="x=1")
    figure = FigureElement(
        element_id="figure", document_order=2, structured_content="chart data"
    )

    for element in (table, formula, figure):
        decision = route_visual_element(element, asset_present=True)
        assert decision.route is VisualRoute.SKIP_EXISTING_STRUCTURE
        assert decision.should_analyze is False


def test_route_keeps_unresolved_asset_in_manual_review() -> None:
    figure = FigureElement(element_id="figure", document_order=0, asset_id="missing")
    decision = route_visual_element(figure, asset_present=False)

    assert decision.route is VisualRoute.MANUAL_REVIEW
    assert decision.risk is VisualRisk.UNKNOWN
    assert decision.should_analyze is False


def test_generic_description_is_accepted_as_non_authoritative_text() -> None:
    request = _request()
    route = VisualRouteDecision(
        VisualRoute.GENERIC_VLM,
        VisualRisk.UNKNOWN,
        "generic fallback",
        True,
    )
    candidate = VisualEnrichmentCandidate(
        description="一张网络拓扑图",
        content_type="figure",
    )

    outcome = select_visual_candidate(request, route, candidate)

    assert outcome.decision is VisualDecision.ACCEPT
    assert outcome.write_to_docir is True
    assert outcome.retrieval_eligible is True


def test_structured_candidate_without_independent_evidence_requires_review() -> None:
    request = _request()
    route = VisualRouteDecision(
        VisualRoute.GENERIC_VLM,
        VisualRisk.UNKNOWN,
        "generic fallback",
        True,
    )
    candidate = VisualEnrichmentCandidate(
        description="节点关系",
        structure={"nodes": [], "edges": []},
    )

    outcome = select_visual_candidate(request, route, candidate)

    assert outcome.decision is VisualDecision.REVIEW
    assert outcome.write_to_docir is False
    assert outcome.retrieval_eligible is False


def test_medium_risk_generic_fallback_requires_review() -> None:
    request = _request()
    route = VisualRouteDecision(
        VisualRoute.GENERIC_VLM,
        VisualRisk.MEDIUM,
        "table fallback",
        True,
    )
    candidate = VisualEnrichmentCandidate(description="表格解释", content_type="table")

    outcome = select_visual_candidate(request, route, candidate)

    assert outcome.decision is VisualDecision.REVIEW


def test_specialist_candidate_requires_and_accepts_evidence() -> None:
    request = _request(VisualRoute.SPECIALIST)
    route = VisualRouteDecision(
        VisualRoute.SPECIALIST,
        VisualRisk.HIGH,
        "specialist adapter",
        True,
    )
    candidate = VisualEnrichmentCandidate(
        description="已确认的有向边",
        structure={"nodes": ["a", "b"], "edges": [["a", "b"]]},
        evidence=(VisualEvidence(kind="pixel", source="edge-endpoint"),),
    )

    outcome = select_visual_candidate(request, route, candidate)

    assert outcome.decision is VisualDecision.ACCEPT


def test_provider_error_is_rejected_without_candidate() -> None:
    request = _request()
    route = VisualRouteDecision(
        VisualRoute.GENERIC_VLM,
        VisualRisk.UNKNOWN,
        "generic fallback",
        True,
    )

    outcome = select_visual_candidate(request, route, error=RuntimeError("offline"))

    assert outcome.decision is VisualDecision.REJECT
    assert outcome.candidate is None
