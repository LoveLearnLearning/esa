"""Pure learning-domain helpers shared by web and contextual tool adapters."""

from __future__ import annotations

from backend.agent.memories.mastery_store import MasteryStore


class EsaMasteryStore(MasteryStore):
    """MasteryStore variant that excludes the target from prerequisites."""

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
            if int(item.get("depth", 0)) > 0 and item.get("kp_id") != kp_id
        ]


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
