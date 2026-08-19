# backend/agent/tools/learning/runtime.py

"""Learning tool handlers using only trusted runtime dependencies."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from backend.agent.tools.context import ToolExecutionContext
from backend.core.services.learning_insight_service import build_recommendation_reasons
from backend.core.utils.models import UserRecord


def _dependency(context: ToolExecutionContext, name: str):
    """Resolve one learning dependency so read-only tools fail independently."""
    value = getattr(context.runtime_dependencies, name, None)
    if value is None:
        raise RuntimeError(f"{name} is not configured")
    return value


def _canonical_kp_id(context: ToolExecutionContext, raw_kp_id: Any) -> str:
    """Resolve aliases before every learning read or write."""
    value = str(raw_kp_id or "").strip()
    if not value:
        raise ValueError("kp_id must not be empty")
    knowledge_graph = _dependency(context, "knowledge_graph_store")
    resolved = knowledge_graph.resolve_kp_id(value)
    if resolved is None:
        raise ValueError(f"unknown knowledge point {value!r}")
    return resolved


def _idempotency_key(
    context: ToolExecutionContext,
    arguments: Mapping[str, Any],
) -> str:
    """Make tool retries in one trusted request harmless."""
    payload = json.dumps(
        {"arguments": dict(arguments)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(
        f"{context.user_id}:{context.request_id}:{payload}".encode("utf-8")
    ).hexdigest()


def _bounded_float(
    arguments: Mapping[str, Any],
    key: str,
    *,
    default: float,
    lower: float,
    upper: float,
) -> float:
    value = float(arguments.get(key, default))
    if not lower <= value <= upper:
        raise ValueError(f"{key} must be between {lower} and {upper}")
    return value


def _bounded_int(
    arguments: Mapping[str, Any],
    key: str,
    *,
    default: int,
    lower: int,
    upper: int,
) -> int:
    value = int(arguments.get(key, default))
    if not lower <= value <= upper:
        raise ValueError(f"{key} must be between {lower} and {upper}")
    return value


def _strict_bool(value: Any, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise ValueError(f"{key} must be a boolean")


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
    user_name = context.username
    if context.conversation_mode == "isolated":
        return {"allowed": False, "action": name, "reason": "isolated mode"}
    if context.conversation_mode != "normal" and name in {
        "record_answer", "record_learning_evidence"
    }:
        return {"saved": False, "reason": "conversation mode forbids writes"}
    if name == "recommend_practice":
        kg = _dependency(context, "knowledge_graph_store")
        mastery = _dependency(context, "mastery_store")
        course = str(arguments["course"])
        weeks = int(arguments["weeks_to_exam"])
        if weeks < 0:
            raise ValueError("weeks_to_exam must be non-negative")
        total = context.total_weeks or UserRecord.TOTAL_WEEKS_DEFAULT
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
        kg = _dependency(context, "knowledge_graph_store")
        mastery = _dependency(context, "mastery_store")
        course = str(arguments.get("course", "")).strip() or None
        return {"allowed": True, **mastery.get_report(
            user_name=user_name, course=course, kg_store=kg
        )}
    if name == "get_mastery_level":
        mastery = _dependency(context, "mastery_store")
        kp_id = _canonical_kp_id(context, arguments["kp_id"])
        record = mastery.get(user_name, kp_id)
        return ({"allowed": True, "has_record": True, **record} if record else {
            "allowed": True, "has_record": False, "user_name": user_name,
            "kp_id": kp_id, "mastery_level": None, "status": "unseen",
            "retention": None, "evidence_confidence": 0.0,
            "practice_count": 0, "correct_count": 0,
        })
    if name == "get_weak_prerequisites":
        kg = _dependency(context, "knowledge_graph_store")
        mastery = _dependency(context, "mastery_store")
        kp_id = _canonical_kp_id(context, arguments["kp_id"])
        items = mastery.get_weak_prerequisites(
            user_name=user_name, kp_id=kp_id, kg_store=kg,
            mastery_threshold=_bounded_float(
                arguments, "mastery_threshold", default=50, lower=0, upper=100
            ),
            max_depth=_bounded_int(
                arguments, "max_depth", default=5, lower=1, upper=10
            ),
        )
        return {"allowed": True, "count": len(items), "weak_prerequisites": items}
    if name == "get_review_timing":
        mastery = _dependency(context, "mastery_store")
        kp_id = _canonical_kp_id(context, arguments["kp_id"])
        return {"allowed": True, **mastery.get_review_timing(
            user_name=user_name, kp_id=kp_id,
            threshold=_bounded_float(
                arguments, "threshold", default=0.7, lower=0.1, upper=0.99
            ),
        )}
    if name in {"record_answer", "record_learning_evidence"}:
        service = _dependency(context, "learning_state_service")
        values = dict(arguments)
        if name == "record_answer":
            values = {
                "kp_id": _canonical_kp_id(context, arguments["kp_id"]),
                "activity_type": "practice",
                "correct": _strict_bool(arguments["correct"], "correct"),
                "evidence_reliability": float(arguments.get("confidence", 1.0)),
            }
        else:
            values["kp_id"] = _canonical_kp_id(context, values["kp_id"])
            for key in ("correct", "independent"):
                if key in values and values[key] is not None:
                    values[key] = _strict_bool(values[key], key)
        result = service.record_event(
            user_name=user_name,
            idempotency_key=_idempotency_key(context, values),
            **values,
        )
        return {
            "saved": True,
            "duplicate": bool(result.get("duplicate")),
            **result,
        }
    if name == "get_learning_evidence_summary":
        store = _dependency(context, "learning_evidence_store")
        raw_kp_id = str(arguments.get("kp_id", "")).strip()
        kp_id = _canonical_kp_id(context, raw_kp_id) if raw_kp_id else None
        return {"allowed": True, **store.get_summary(
            user_name, kp_id=kp_id,
            limit=_bounded_int(arguments, "limit", default=50, lower=1, upper=200),
        )}
    raise KeyError(name)
