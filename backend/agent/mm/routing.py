"""Deterministic routing policy for DocIR visual elements."""

from __future__ import annotations

from backend.agent.DocIR import FigureElement, FormulaElement, TableElement

from .contracts import VisualRisk, VisualRoute, VisualRouteDecision


MM_VISUAL_ROUTING_VERSION = "mm-visual-routing-0.1"


def route_visual_element(element: object, *, asset_present: bool) -> VisualRouteDecision:
    """Choose a conservative visual route without inspecting image pixels."""

    if isinstance(element, TableElement) and (element.html or "").strip():
        return VisualRouteDecision(
            VisualRoute.SKIP_EXISTING_STRUCTURE,
            VisualRisk.LOW,
            "table already has machine-readable HTML",
            False,
        )
    if isinstance(element, FormulaElement) and (element.latex or "").strip():
        return VisualRouteDecision(
            VisualRoute.SKIP_EXISTING_STRUCTURE,
            VisualRisk.LOW,
            "formula already has machine-readable LaTeX",
            False,
        )
    if isinstance(element, FigureElement) and (
        element.structured_content or ""
    ).strip():
        return VisualRouteDecision(
            VisualRoute.SKIP_EXISTING_STRUCTURE,
            VisualRisk.LOW,
            "figure already has machine-readable structure",
            False,
        )
    if not isinstance(element, (TableElement, FormulaElement, FigureElement)):
        return VisualRouteDecision(
            VisualRoute.MANUAL_REVIEW,
            VisualRisk.UNKNOWN,
            "element type is not supported by visual enrichment",
            False,
        )
    if not asset_present:
        return VisualRouteDecision(
            VisualRoute.MANUAL_REVIEW,
            VisualRisk.HIGH,
            "visual element has no verifiable asset",
            False,
        )

    risk = (
        VisualRisk.MEDIUM
        if isinstance(element, (TableElement, FormulaElement))
        else VisualRisk.LOW
    )
    return VisualRouteDecision(
        VisualRoute.GENERIC_VLM,
        risk,
        "visual asset needs a non-authoritative semantic description",
        True,
    )
