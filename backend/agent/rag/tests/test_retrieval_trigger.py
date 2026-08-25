"""Tests for the reserved automatic retrieval trigger extension point."""

from __future__ import annotations

import asyncio

from backend.agent.rag.retrieval_trigger import (
    DisabledIntentTriggeredRetrieval,
    RetrievalTrigger,
    RetrievalTriggerContext,
    RetrievalTriggerMode,
)


def test_disabled_intent_trigger_never_requests_retrieval() -> None:
    trigger = DisabledIntentTriggeredRetrieval()
    context = RetrievalTriggerContext(
        current_message="请解释虚拟内存",
        workspace_type="learning",
        task_mode="concept",
        knowledge_sources=("personal", "public"),
    )

    decision = asyncio.run(trigger.decide(context))

    assert trigger.mode is RetrievalTriggerMode.INTENT_TRIGGERED
    assert decision.should_retrieve is False
    assert decision.knowledge_sources == ()
    assert decision.reason == "intent_triggered_retrieval_disabled"


def test_disabled_intent_trigger_implements_protocol() -> None:
    trigger: RetrievalTrigger = DisabledIntentTriggeredRetrieval()

    assert callable(trigger.decide)
