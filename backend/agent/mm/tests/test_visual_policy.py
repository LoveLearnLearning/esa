"""Deterministic visual routing and selection policy tests."""

from backend.agent.DocIR import FigureElement, FormulaElement, TableElement
from backend.agent.mm.contracts import (
    VisualDecision,
    VisualEnrichmentCandidate,
    VisualEnrichmentRequest,
    VisualRoute,
)
from backend.agent.mm.routing import route_visual_element
from backend.agent.mm.selection import select_visual_candidate


def _request(route):
    return VisualEnrichmentRequest(
        document_id="doc",
        element_id="element",
        asset_id="asset",
        asset_sha256="a" * 64,
        media_type="image/png",
        asset_path="asset.png",
        route=route.route,
        risk=route.risk,
    )


def test_existing_machine_readable_structure_skips_vlm():
    table = TableElement(element_id="t1", document_order=0, html="<table></table>")
    formula = FormulaElement(element_id="f1", document_order=1, latex="x^2")
    figure = FigureElement(
        element_id="g1", document_order=2, structured_content="nodes: []"
    )

    for element in (table, formula, figure):
        decision = route_visual_element(element, asset_present=True)
        assert decision.route is VisualRoute.SKIP_EXISTING_STRUCTURE
        assert decision.should_analyze is False


def test_missing_asset_requires_review_and_generic_description_is_accepted():
    figure = FigureElement(element_id="g1", document_order=0, asset_id="asset")
    missing = route_visual_element(figure, asset_present=False)
    assert missing.route is VisualRoute.MANUAL_REVIEW
    assert missing.should_analyze is False

    route = route_visual_element(figure, asset_present=True)
    outcome = select_visual_candidate(
        _request(route),
        route,
        VisualEnrichmentCandidate(description="一张展示三阶段处理流程的架构图"),
    )
    assert outcome.decision is VisualDecision.ACCEPT
    assert outcome.write_to_docir is True
    assert outcome.retrieval_eligible is True


def test_unsupported_structure_claims_are_held_for_review():
    figure = FigureElement(element_id="g1", document_order=0, asset_id="asset")
    route = route_visual_element(figure, asset_present=True)
    outcome = select_visual_candidate(
        _request(route),
        route,
        VisualEnrichmentCandidate(
            description="流程图",
            structure={"edges": [{"from": "a", "to": "b"}]},
        ),
    )
    assert outcome.decision is VisualDecision.REVIEW
    assert outcome.write_to_docir is False
