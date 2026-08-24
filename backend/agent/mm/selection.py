"""Conservative admission policy for visual-enrichment candidates."""

from __future__ import annotations

from .contracts import (
    VisualDecision,
    VisualEnrichmentCandidate,
    VisualEnrichmentOutcome,
    VisualEnrichmentRequest,
    VisualRoute,
    VisualRouteDecision,
)


MM_VISUAL_SELECTION_VERSION = "mm-visual-selection-0.1"


def select_visual_candidate(
    request: VisualEnrichmentRequest,
    route: VisualRouteDecision,
    candidate: VisualEnrichmentCandidate | None,
    *,
    error: Exception | None = None,
) -> VisualEnrichmentOutcome:
    """Admit descriptive text while holding unsupported structure for review."""

    if route.route is VisualRoute.MANUAL_REVIEW:
        return VisualEnrichmentOutcome(
            request,
            route,
            VisualDecision.REVIEW,
            candidate=candidate,
            reason=route.reason,
        )
    if route.route is VisualRoute.SKIP_EXISTING_STRUCTURE:
        return VisualEnrichmentOutcome(
            request,
            route,
            VisualDecision.REJECT,
            reason=route.reason,
        )
    if error is not None or candidate is None:
        return VisualEnrichmentOutcome(
            request,
            route,
            VisualDecision.REJECT,
            reason=(
                f"visual provider failed: {type(error).__name__}"
                if error is not None
                else "visual provider returned no candidate"
            ),
        )
    if candidate.validator_findings or candidate.unresolved_items:
        return VisualEnrichmentOutcome(
            request,
            route,
            VisualDecision.REVIEW,
            candidate=candidate,
            reason="candidate contains unresolved or validator findings",
        )
    if candidate.structure is not None and not candidate.evidence:
        return VisualEnrichmentOutcome(
            request,
            route,
            VisualDecision.REVIEW,
            candidate=candidate,
            reason="structured visual claims require independent evidence",
        )
    return VisualEnrichmentOutcome(
        request,
        route,
        VisualDecision.ACCEPT,
        candidate=candidate,
        reason="descriptive VLM output accepted as non-authoritative text",
        write_to_docir=True,
        retrieval_eligible=True,
    )
