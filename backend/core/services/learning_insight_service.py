"""Learning insight queries shared by HTTP and agent adapters."""

from __future__ import annotations

from backend.core.utils.models import UserRecord


def build_recommendation_reasons(
    point: dict,
    weak_prereqs: list[dict],
    weeks_to_exam: int,
    total_weeks: int,
) -> list[str]:
    reasons: list[str] = []
    raw_mastery = point.get("mastery_level")
    mastery = None if raw_mastery is None else float(raw_mastery)
    weight = float(point.get("weight", 0.0))
    if mastery is None:
        reasons.append("尚无学习证据")
    elif mastery < 50.0:
        reasons.append(f"掌握度低(mastery={mastery:.1f})")
    if weight >= 0.7:
        reasons.append(f"考试权重高(weight={weight:.2f})")
    if total_weeks > 0 and weeks_to_exam <= total_weeks / 4:
        reasons.append(f"距期末仅 {weeks_to_exam} 周")
    if weak_prereqs:
        reasons.append(f"前置薄弱({len(weak_prereqs)} 个前置掌握度<50)")
    return reasons or ["综合优先级排序推荐"]


class LearningInsightService:
    def __init__(self, knowledge_graph_store, mastery_store) -> None:
        self.knowledge_graph_store = knowledge_graph_store
        self.mastery_store = mastery_store

    def mastery_report(self, *, user_name: str, course: str = "") -> dict:
        return {
            "allowed": True,
            **self.mastery_store.get_report(
                user_name=user_name,
                course=course.strip() or None,
                kg_store=self.knowledge_graph_store,
            ),
        }

    def practice_recommendations(
        self,
        *,
        user_name: str,
        course: str,
        weeks_to_exam: int,
        total_weeks: int | None,
    ) -> dict:
        weeks = int(weeks_to_exam)
        total = total_weeks or UserRecord.TOTAL_WEEKS_DEFAULT
        ranking = self.mastery_store.get_priority_ranking(
            user_name=user_name,
            course=course,
            weeks_to_exam=weeks,
            total_weeks=total,
            kg_store=self.knowledge_graph_store,
        )
        recommendations = []
        for point in ranking[:5]:
            weak = self.mastery_store.get_weak_prerequisites(
                user_name=user_name,
                kp_id=point["kp_id"],
                kg_store=self.knowledge_graph_store,
            )
            recommendations.append(
                {
                    **point,
                    "reasons": build_recommendation_reasons(point, weak, weeks, total),
                    "weak_prerequisites": weak,
                }
            )
        return {
            "allowed": True,
            "user_name": user_name,
            "course": course,
            "count": len(recommendations),
            "recommendations": recommendations,
            **({"note": f"未找到课程 {course!r} 的知识点"} if not ranking else {}),
        }
