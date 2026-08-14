"""Adapter retaining the existing deterministic learning pedagogy router."""

from __future__ import annotations

from backend.agent.learning.pedagogy_router import PedagogyRouter
from backend.agent.skills.catalog import ScopedSkillView
from backend.agent.workspaces.context_composer import StrategyAugmentation
from backend.agent.workspaces.models import AgentTurnInput


class LearningAdapter:
    def augment(
        self,
        turn: AgentTurnInput,
        skills: ScopedSkillView,
        profile_snapshot=None,
    ) -> StrategyAugmentation:
        if turn.route.workspace_type != "learning":
            return StrategyAugmentation()
        try:
            decision = PedagogyRouter.route(
                turn.current_message,
                history=[dict(item) for item in turn.history],
                profile=profile_snapshot,
            )
            body = (
                skills.load(decision.skill_name)
                if decision.skill_name and decision.skill_name in skills.names
                else None
            )
            return StrategyAugmentation(decision.to_prompt_context(body))
        except (KeyError, TypeError, ValueError):
            return StrategyAugmentation()

