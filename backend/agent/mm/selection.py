# backend/agent/mm/selection.py

"""无标签视觉候选准入。

选择器只看运行时契约、独立证据和校验结果；不读取参考答案、人工评分
或模型自报置信度。
"""

from __future__ import annotations

from .contracts import (
    VisualDecision,
    VisualEnrichmentCandidate,
    VisualEnrichmentOutcome,
    VisualEnrichmentRequest,
    VisualRisk,
    VisualRoute,
    VisualRouteDecision,
)


MM_VISUAL_SELECTION_VERSION = "mm-visual-selection-0.1"


def select_visual_candidate(
    request: VisualEnrichmentRequest,
    route_decision: VisualRouteDecision,
    candidate: VisualEnrichmentCandidate | None = None,
    *,
    error: Exception | None = None,
) -> VisualEnrichmentOutcome:
    """根据无标签证据决定候选是否可写入 DocIR。"""

    if error is not None:
        return VisualEnrichmentOutcome(
            request=request,
            route_decision=route_decision,
            decision=VisualDecision.REJECT,
            reason=f"visual provider failed: {type(error).__name__}",
        )
    if route_decision.route is VisualRoute.MANUAL_REVIEW:
        if candidate is not None:
            return _review(request, route_decision, candidate, route_decision.reason)
        return VisualEnrichmentOutcome(
            request=request,
            route_decision=route_decision,
            decision=VisualDecision.REVIEW,
            reason=route_decision.reason,
        )
    if not route_decision.should_analyze:
        decision = (
            VisualDecision.REVIEW
            if route_decision.route is VisualRoute.MANUAL_REVIEW
            else VisualDecision.REJECT
        )
        return VisualEnrichmentOutcome(
            request=request,
            route_decision=route_decision,
            decision=decision,
            reason=route_decision.reason,
        )
    if candidate is None:
        return VisualEnrichmentOutcome(
            request=request,
            route_decision=route_decision,
            decision=VisualDecision.REJECT,
            reason="visual provider returned no candidate",
        )
    if route_decision.route is VisualRoute.GENERIC_VLM and route_decision.risk in {
        VisualRisk.MEDIUM,
        VisualRisk.HIGH,
    }:
        return _review(
            request,
            route_decision,
            candidate,
            "generic VLM output for a medium/high-risk route requires review",
        )
    if candidate.structure is not None:
        if route_decision.route is not VisualRoute.SPECIALIST:
            return _review(
                request,
                route_decision,
                candidate,
                "structured visual claims require a specialist route",
            )
        if not candidate.evidence:
            return _review(
                request,
                route_decision,
                candidate,
                "structured visual claims have no independent evidence",
            )
    if candidate.unresolved_items or candidate.validator_findings:
        return _review(
            request,
            route_decision,
            candidate,
            "candidate contains unresolved items or validator findings",
        )
    return VisualEnrichmentOutcome(
        request=request,
        route_decision=route_decision,
        decision=VisualDecision.ACCEPT,
        candidate=candidate,
        reason="non-structural visual description passed the current gate",
        write_to_docir=True,
        retrieval_eligible=True,
    )


def _review(
    request: VisualEnrichmentRequest,
    route_decision: VisualRouteDecision,
    candidate: VisualEnrichmentCandidate,
    reason: str,
) -> VisualEnrichmentOutcome:
    return VisualEnrichmentOutcome(
        request=request,
        route_decision=route_decision,
        decision=VisualDecision.REVIEW,
        candidate=candidate,
        reason=reason,
    )
