# backend/agent/tools/learning/runtime.py

"""Learning tool handlers using only trusted runtime dependencies."""

from __future__ import annotations

from typing import Any, Mapping

from backend.agent.tools.context import ToolExecutionContext
from backend.agent.tools.learning.mastery import build_recommendation_reasons
from backend.core.utils.models import UserRecord


def _deps(context: ToolExecutionContext):
    """处理 `_deps` 相关逻辑。"""
    deps = context.runtime_dependencies
    if not deps.username:
        raise RuntimeError("learning tools require a trusted username")
    if deps.knowledge_graph_store is None or deps.mastery_store is None:
        raise RuntimeError("learning stores are not configured")
    return deps


def execute_learning_tool(
    context: ToolExecutionContext, name: str, arguments: Mapping[str, Any]
) -> dict[str, Any]:
    """执行 `learning tool` 相关数据。

    Args:
        context: ToolExecutionContext => `context` 参数。
        name: str => `name` 参数。
        arguments: Mapping[str, Any] => `arguments` 参数。

    Returns:
        dict[str, Any] => 处理结果。
    """
    deps = _deps(context)
    user_name = deps.username
    if context.conversation_mode == "isolated" and name != "record_answer":
        return {"allowed": False, "action": name, "reason": "isolated mode"}
    if context.conversation_mode != "normal" and name in {
        "record_answer", "record_learning_evidence"
    }:
        return {"saved": False, "reason": "conversation mode forbids writes"}
    kg, mastery = deps.knowledge_graph_store, deps.mastery_store

    if name == "recommend_practice":
        course = str(arguments["course"])
        weeks = int(arguments["weeks_to_exam"])
        total = deps.total_weeks or UserRecord.TOTAL_WEEKS_DEFAULT
        ranking = mastery.get_priority_ranking(
            user_name=user_name, course=course, weeks_to_exam=weeks,
            total_weeks=total, kg_store=kg,
        )
        recommendations = []
        for point in ranking[:5]:
            weak = mastery.get_weak_prerequisites(
                user_name=user_name, kp_id=point["kp_id"], kg_store=kg
            )
            recommendations.append({
                **point,
                "reasons": build_recommendation_reasons(point, weak, weeks, total),
                "weak_prerequisites": weak,
            })
        return {
            "allowed": True, "user_name": user_name, "course": course,
            "count": len(recommendations), "recommendations": recommendations,
            **({"note": f"未找到课程 {course!r} 的知识点"} if not ranking else {}),
        }
    if name == "get_mastery_report":
        course = str(arguments.get("course", "")).strip() or None
        return {"allowed": True, **mastery.get_report(
            user_name=user_name, course=course, kg_store=kg
        )}
    if name == "get_mastery_level":
        kp_id = str(arguments["kp_id"])
        record = mastery.get(user_name, kp_id)
        return ({"allowed": True, "has_record": True, **record} if record else {
            "allowed": True, "has_record": False, "user_name": user_name,
            "kp_id": kp_id, "mastery_level": None, "status": "unseen",
            "retention": None, "evidence_confidence": 0.0,
            "practice_count": 0, "correct_count": 0,
        })
    if name == "get_weak_prerequisites":
        items = mastery.get_weak_prerequisites(
            user_name=user_name, kp_id=str(arguments["kp_id"]), kg_store=kg,
            mastery_threshold=float(arguments.get("mastery_threshold", 50)),
            max_depth=int(arguments.get("max_depth", 5)),
        )
        return {"allowed": True, "count": len(items), "weak_prerequisites": items}
    if name == "get_review_timing":
        return {"allowed": True, **mastery.get_review_timing(
            user_name=user_name, kp_id=str(arguments["kp_id"]),
            threshold=float(arguments.get("threshold", 0.7)),
        )}
    if name in {"record_answer", "record_learning_evidence"}:
        service = deps.learning_state_service
        if service is None:
            raise RuntimeError("learning state service is not configured")
        values = dict(arguments)
        if name == "record_answer":
            values = {
                "kp_id": str(arguments["kp_id"]), "activity_type": "practice",
                "correct": bool(arguments["correct"]),
                "evidence_reliability": float(arguments.get("confidence", 1.0)),
            }
        return {"saved": True, **service.record_event(user_name=user_name, **values)}
    if name == "get_learning_evidence_summary":
        store = deps.learning_evidence_store
        if store is None:
            raise RuntimeError("learning evidence store is not configured")
        return {"allowed": True, **store.get_summary(
            user_name, kp_id=str(arguments.get("kp_id", "")).strip() or None,
            limit=int(arguments.get("limit", 50)),
        )}
    raise KeyError(name)
