"""Extension contracts for deciding whether retrieval should run automatically."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class RetrievalTriggerMode(str, Enum):
    """Supported retrieval invocation policies."""

    ON_DEMAND = "on_demand"
    INTENT_TRIGGERED = "intent_triggered"


@dataclass(frozen=True, slots=True)
class RetrievalTriggerContext:
    """Trusted turn information available to a future trigger implementation."""

    current_message: str
    workspace_type: str
    task_mode: str | None
    knowledge_sources: tuple[str, ...]
    personal_knowledge_base_id: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalTriggerDecision:
    """Result of evaluating an automatic retrieval trigger."""

    should_retrieve: bool
    knowledge_sources: tuple[str, ...] = ()
    reason: str = ""


class RetrievalTrigger(Protocol):
    """Asynchronous extension point for future intent-triggered retrieval."""

    async def decide(
        self,
        context: RetrievalTriggerContext,
    ) -> RetrievalTriggerDecision:
        """Return whether retrieval should run for the supplied turn."""
        ...


@dataclass(frozen=True, slots=True)
class DisabledIntentTriggeredRetrieval:
    """Reserved implementation that keeps intent-triggered retrieval disabled."""

    mode: RetrievalTriggerMode = RetrievalTriggerMode.INTENT_TRIGGERED

    async def decide(
        self,
        context: RetrievalTriggerContext,
    ) -> RetrievalTriggerDecision:
        """Never trigger retrieval until an implementation is explicitly wired."""

        del context
        return RetrievalTriggerDecision(
            should_retrieve=False,
            reason="intent_triggered_retrieval_disabled",
        )
