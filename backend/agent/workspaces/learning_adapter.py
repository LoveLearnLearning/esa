# backend/agent/workspaces/learning_adapter.py

"""Adapter retaining the existing deterministic learning pedagogy router."""

from __future__ import annotations

from backend.agent.learning.pedagogy_router import PedagogyRouter
from backend.agent.skills.catalog import ScopedSkillView
from backend.agent.workspaces.context_composer import StrategyAugmentation
from backend.agent.workspaces.models import AgentTurnInput


class LearningAdapter:
    """封装 `LearningAdapter` 的状态与行为。"""

    _AUTO_LOAD_SKILLS = frozenset(
        {
            "adaptive_practice",
            "homework_review",
            "progressive_hint",
            "teach_back",
        }
    )
    def augment(
        self,
        turn: AgentTurnInput,
        skills: ScopedSkillView,
        profile_snapshot=None,
    ) -> StrategyAugmentation:
        """处理 `augment` 相关逻辑。

        Args:
            turn: AgentTurnInput => `turn` 参数。
            skills: ScopedSkillView => `skills` 参数。
            profile_snapshot: object => `profile_snapshot` 参数。

        Returns:
            StrategyAugmentation => 处理结果。
        """
        if turn.route.workspace_type != "learning":
            return StrategyAugmentation()
        try:
            decision = PedagogyRouter.route(
                turn.current_message,
                history=[dict(item) for item in turn.history],
                profile=profile_snapshot,
                resolved_kp_ids=turn.learning_context.resolved_kp_ids,
                pending_practice_kp_id=turn.learning_context.pending_practice_kp_id,
            )
            body = (
                skills.load(decision.skill_name)
                if (
                    decision.skill_name
                    and decision.skill_name in self._AUTO_LOAD_SKILLS
                    and decision.skill_name in skills.names
                )
                else None
            )
            return StrategyAugmentation(decision.to_prompt_context(body))
        except (KeyError, TypeError, ValueError):
            return StrategyAugmentation()
