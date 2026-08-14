from __future__ import annotations

from typing import cast

import pytest

from backend.agent.rag.agent_api import get_retrieval_service, reset_retrieval_service
from backend.agent.rag.lifecycle import RAGApplicationLifecycle
from backend.agent.rag.retrieval.service import RetrievalService


def test_rag_lifecycle_explicitly_configures_and_resets_service() -> None:
    reset_retrieval_service()
    service = cast(RetrievalService, object())
    lifecycle = RAGApplicationLifecycle(enabled=True, factory=lambda: service)

    assert lifecycle.start() is service
    assert get_retrieval_service() is service
    lifecycle.close()

    with pytest.raises(RuntimeError, match="not configured"):
        get_retrieval_service()


def test_disabled_rag_lifecycle_does_not_call_factory() -> None:
    lifecycle = RAGApplicationLifecycle(
        enabled=False,
        factory=lambda: pytest.fail("factory must not be called"),
    )
    assert lifecycle.start() is None


def test_rag_lifecycle_warms_service_once() -> None:
    reset_retrieval_service()

    class WarmService:
        calls = 0

        def warmup(self) -> None:
            self.calls += 1

    service = WarmService()
    lifecycle = RAGApplicationLifecycle(
        enabled=True,
        factory=lambda: cast(RetrievalService, service),
    )

    assert lifecycle.start() is service
    assert lifecycle.start() is service
    assert service.calls == 1
    lifecycle.close()
