# backend/agent/mm/routing.py

"""确定性视觉资产路由。

第一阶段不引入图片分类模型。路由只相信 DocIR 已明确提供的结构，
未知图片类别保持 unknown 风险，不会因为模型标签而自动升级为结构事实。
"""

from __future__ import annotations

from backend.agent.DocIR import FigureElement, FormulaElement, TableElement

from .contracts import VisualRisk, VisualRoute, VisualRouteDecision


MM_VISUAL_ROUTING_VERSION = "mm-visual-routing-0.1"


def route_visual_element(
    element: object,
    *,
    asset_present: bool,
) -> VisualRouteDecision:
    """根据现有 DocIR 结构选择视觉资产路线。

    这里不读取 VLM 输出，也不把 ``content_type`` 当成调用前分类器。
    """

    if isinstance(element, TableElement) and element.html and element.html.strip():
        return VisualRouteDecision(
            VisualRoute.SKIP_EXISTING_STRUCTURE,
            VisualRisk.LOW,
            "table already has HTML structure",
            False,
        )
    if isinstance(element, FormulaElement) and element.latex and element.latex.strip():
        return VisualRouteDecision(
            VisualRoute.SKIP_EXISTING_STRUCTURE,
            VisualRisk.LOW,
            "formula already has LaTeX structure",
            False,
        )
    if isinstance(element, FigureElement) and element.structured_content and element.structured_content.strip():
        return VisualRouteDecision(
            VisualRoute.SKIP_EXISTING_STRUCTURE,
            VisualRisk.LOW,
            "figure already has structured content",
            False,
        )
    if not asset_present or not getattr(element, "asset_id", None):
        return VisualRouteDecision(
            VisualRoute.MANUAL_REVIEW,
            VisualRisk.UNKNOWN,
            "visual element has no resolvable asset",
            False,
        )
    if isinstance(element, FigureElement):
        return VisualRouteDecision(
            VisualRoute.GENERIC_VLM,
            VisualRisk.UNKNOWN,
            "figure lacks verified structured content; use generic VLM description",
            True,
        )
    if isinstance(element, (TableElement, FormulaElement)):
        return VisualRouteDecision(
            VisualRoute.GENERIC_VLM,
            VisualRisk.MEDIUM,
            "structured table/formula content is unavailable; use generic fallback",
            True,
        )
    return VisualRouteDecision(
        VisualRoute.MANUAL_REVIEW,
        VisualRisk.UNKNOWN,
        "element is not a supported visual enrichment type",
        False,
    )
