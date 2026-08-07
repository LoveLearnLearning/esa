# backend/agent/tools/mastery_tools.py
#
# 向 LLM 暴露 MasteryStore + KnowledgeGraphStore 的受控数据能力。
# 所有工具从 ContextVar 获取当前用户，避免模型跨用户读取/写入数据。
# 读取工具遵守 isolated 模式；写入工具遵守 no_write/isolated 模式。

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import Any

from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.mastery_store import MasteryStore
from backend.agent.tools.memory_tools import (
    get_current_user,
    memory_read_allowed,
    memory_write_allowed,
)
from backend.agent.tools.tools import tr
from backend.core.utils.models import UserRecord

MEMORIES_DIR = Path(__file__).resolve().parent.parent / "memories"

class EsaMasteryStore(MasteryStore):
    """ESA 运行时 MasteryStore：收紧前置知识点语义。"""

    def get_weak_prerequisites(
        self,
        user_name: str,
        kp_id: str,
        kg_store,
        mastery_threshold: float = 50.0,
        max_depth: int = 5,
    ) -> list[dict]:
        items = super().get_weak_prerequisites(
            user_name=user_name,
            kp_id=kp_id,
            kg_store=kg_store,
            mastery_threshold=mastery_threshold,
            max_depth=max_depth,
        )
        return [
            item
            for item in items
            if int(item.get("depth", 0)) > 0
            and item.get("kp_id") != kp_id
        ]


kg_store = KnowledgeGraphStore(
    database_path=MEMORIES_DIR / "data" / "knowledge_graph.db",
)
mastery_store = EsaMasteryStore(
    database_path=MEMORIES_DIR / "data" / "mastery.db",
)

current_total_weeks: ContextVar[int | None] = ContextVar(
    "current_total_weeks",
    default=None,
)


def set_current_total_weeks(total_weeks: int) -> None:
    """由 Agent 在每轮开始时注入用户学期总周数。"""
    current_total_weeks.set(total_weeks)


def _read_blocked_payload(action: str) -> dict[str, Any]:
    return {
        "allowed": False,
        "action": action,
        "reason": "当前会话为 isolated 模式，禁止读取长期学习状态",
    }


def _build_reasons(
    point: dict,
    weak_prereqs: list[dict],
    weeks_to_exam: int,
    total_weeks: int,
) -> list[str]:
    reasons: list[str] = []

    mastery = float(point.get("mastery_level", 50.0))
    weight = float(point.get("weight", 0.0))

    if mastery < 50.0:
        reasons.append(f"掌握度低(mastery={mastery:.1f})")

    if weight >= 0.7:
        reasons.append(f"考试权重高(weight={weight:.2f})")

    if total_weeks > 0 and weeks_to_exam <= total_weeks / 4:
        reasons.append(f"距期末仅 {weeks_to_exam} 周")

    if weak_prereqs:
        reasons.append(f"前置薄弱({len(weak_prereqs)} 个前置掌握度<50)")

    if not reasons:
        reasons.append("综合优先级排序推荐")

    return reasons


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "recommend_practice",
            "description": (
                "推荐当前用户在某课程中需要重点练习的知识点；"
                "综合掌握度、考试权重、距期末时间和前置依赖。"
                "当用户问今天练什么、制定刷题计划或请求练习推荐时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "course": {
                        "type": "string",
                        "description": "课程名，例如 数据结构 / 操作系统",
                    },
                    "weeks_to_exam": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "距考试周数，0 表示本周考试",
                    },
                },
                "required": ["course", "weeks_to_exam"],
            },
        },
    }
)
def recommend_practice(
    course: str,
    weeks_to_exam: int,
) -> dict[str, Any]:
    user_name = get_current_user()

    if not memory_read_allowed():
        return {
            **_read_blocked_payload("recommend_practice"),
            "user_name": user_name,
            "course": course,
            "count": 0,
            "recommendations": [],
        }

    total_weeks = current_total_weeks.get() or UserRecord.TOTAL_WEEKS_DEFAULT

    ranking = mastery_store.get_priority_ranking(
        user_name=user_name,
        course=course,
        weeks_to_exam=weeks_to_exam,
        total_weeks=total_weeks,
        kg_store=kg_store,
    )

    if not ranking:
        return {
            "allowed": True,
            "user_name": user_name,
            "course": course,
            "count": 0,
            "recommendations": [],
            "note": f"未找到课程 {course!r} 的知识点，请确认课程名",
        }

    recommendations: list[dict[str, Any]] = []
    for point in ranking[:5]:
        weak_prereqs = mastery_store.get_weak_prerequisites(
            user_name=user_name,
            kp_id=point["kp_id"],
            kg_store=kg_store,
        )
        reasons = _build_reasons(
            point=point,
            weak_prereqs=weak_prereqs,
            weeks_to_exam=weeks_to_exam,
            total_weeks=total_weeks,
        )
        recommendations.append(
            {
                "kp_id": point["kp_id"],
                "name": point["name"],
                "course": point["course"],
                "weight": point["weight"],
                "mastery_level": point["mastery_level"],
                "practice_count": point["practice_count"],
                "priority": point["priority"],
                "reasons": reasons,
                "weak_prerequisites": weak_prereqs,
            }
        )

    return {
        "allowed": True,
        "user_name": user_name,
        "course": course,
        "count": len(recommendations),
        "recommendations": recommendations,
    }


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "get_mastery_report",
            "description": (
                "获取当前用户的掌握度报告，包含平均掌握度、薄弱/优势知识点"
                "以及超过 7 天未练习的知识点。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "course": {
                        "type": "string",
                        "description": "课程名；留空返回全部课程",
                    },
                },
                "required": [],
            },
        },
    }
)
def get_mastery_report(course: str = "") -> dict[str, Any]:
    user_name = get_current_user()

    if not memory_read_allowed():
        return {
            **_read_blocked_payload("get_mastery_report"),
            "user_name": user_name,
            "course": course or None,
            "total_points": 0,
            "avg_mastery": 0.0,
            "weak_points": [],
            "strong_points": [],
            "stale_points": [],
        }

    course_arg = course.strip() if course else None
    report = mastery_store.get_report(
        user_name=user_name,
        course=course_arg,
        kg_store=kg_store,
    )
    return {"allowed": True, **report}


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "get_mastery_level",
            "description": (
                "读取当前用户某个知识点的掌握度和练习统计；"
                "当 Skill 需要针对单个知识点调节讲解深度时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kp_id": {
                        "type": "string",
                        "description": "知识点 id",
                    }
                },
                "required": ["kp_id"],
            },
        },
    }
)
def get_mastery_level(kp_id: str) -> dict[str, Any]:
    user_name = get_current_user()
    if not memory_read_allowed():
        return {
            **_read_blocked_payload("get_mastery_level"),
            "user_name": user_name,
            "kp_id": kp_id,
        }

    record = mastery_store.get(user_name, kp_id)
    if record is None:
        return {
            "allowed": True,
            "user_name": user_name,
            "kp_id": kp_id,
            "mastery_level": mastery_store.DEFAULT_MASTERY,
            "practice_count": 0,
            "correct_count": 0,
            "has_record": False,
        }

    return {
        "allowed": True,
        "has_record": True,
        **record,
    }


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "get_weak_prerequisites",
            "description": (
                "追溯某知识点的薄弱前置知识点，按依赖深度优先返回；"
                "用于判断应该直接练当前知识点还是先补前置。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kp_id": {
                        "type": "string",
                        "description": "目标知识点 id",
                    },
                    "mastery_threshold": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 100,
                        "description": "低于该掌握度视为薄弱，默认 50",
                    },
                    "max_depth": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "最大追溯深度，默认 5",
                    },
                },
                "required": ["kp_id"],
            },
        },
    }
)
def get_weak_prerequisites(
    kp_id: str,
    mastery_threshold: float = 50.0,
    max_depth: int = 5,
) -> dict[str, Any]:
    user_name = get_current_user()
    if not memory_read_allowed():
        return {
            **_read_blocked_payload("get_weak_prerequisites"),
            "user_name": user_name,
            "kp_id": kp_id,
            "count": 0,
            "weak_prerequisites": [],
        }

    items = mastery_store.get_weak_prerequisites(
        user_name=user_name,
        kp_id=kp_id,
        kg_store=kg_store,
        mastery_threshold=mastery_threshold,
        max_depth=max_depth,
    )
    return {
        "allowed": True,
        "user_name": user_name,
        "kp_id": kp_id,
        "count": len(items),
        "weak_prerequisites": items,
    }


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "get_review_timing",
            "description": (
                "预测某知识点当前回忆概率以及推荐复习日期；"
                "用于学习计划和间隔复习，而不是替代掌握度。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kp_id": {
                        "type": "string",
                        "description": "知识点 id",
                    },
                    "threshold": {
                        "type": "number",
                        "minimum": 0.1,
                        "maximum": 0.99,
                        "description": "回忆概率低于该阈值时触发复习，默认 0.7",
                    },
                },
                "required": ["kp_id"],
            },
        },
    }
)
def get_review_timing(
    kp_id: str,
    threshold: float = 0.7,
) -> dict[str, Any]:
    user_name = get_current_user()
    if not memory_read_allowed():
        return {
            **_read_blocked_payload("get_review_timing"),
            "user_name": user_name,
            "kp_id": kp_id,
        }

    result = mastery_store.get_review_timing(
        user_name=user_name,
        kp_id=kp_id,
        threshold=threshold,
    )
    return {
        "allowed": True,
        "user_name": user_name,
        "kp_id": kp_id,
        **result,
    }


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "record_answer",
            "description": (
                "记录当前用户一次练习结果并更新知识点掌握度。"
                "confidence 是这次答案作为掌握证据的可靠性权重，"
                "不是学生主观自信；学生自评信心应记录到 record_learning_evidence。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kp_id": {
                        "type": "string",
                        "description": "知识点 id",
                    },
                    "correct": {
                        "type": "boolean",
                        "description": "是否答对",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": (
                            "证据可靠性 0-1；"
                            "填空/编程/证明通常高，选择题可能因猜测而降低。默认 1.0"
                        ),
                    },
                },
                "required": ["kp_id", "correct"],
            },
        },
    }
)
def record_answer(
    kp_id: str,
    correct: bool,
    confidence: float = 1.0,
) -> dict[str, Any]:
    user_name = get_current_user()

    if not memory_write_allowed():
        return {
            "user_name": user_name,
            "kp_id": kp_id,
            "saved": False,
            "reason": "当前会话为 no_write/isolated 模式，禁止记录练习结果",
        }

    result = mastery_store.record_answer(
        user_name=user_name,
        kp_id=kp_id,
        correct=correct,
        confidence=confidence,
    )
    return {"saved": True, **result}
