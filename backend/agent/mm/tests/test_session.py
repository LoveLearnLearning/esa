# backend/agent/mm/tests/test_session.py

"""验证 `session` 相关行为与回归场景。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

from backend.agent.mm.contracts import PreparedAttachment
from backend.agent.mm.session import MultimodalSessionService
from backend.agent.mm.service import MultimodalIngestionService


class _FakeIngestion:
    """封装 `_FakeIngestion` 的状态与行为。"""
    async def prepare_files(self, _paths: object) -> tuple[PreparedAttachment, ...]:
        """准备 `files` 相关数据。"""
        attachment = SimpleNamespace(
            document=SimpleNamespace(document_id="doc-1"),
            context_for=lambda query, _level: f"context:{query}",
        )
        return (cast(PreparedAttachment, attachment),)


def test_multimodal_session_owns_attachment_handles() -> None:
    """验证 `multimodal_session_owns_attachment_handles` 场景。"""
    sessions = MultimodalSessionService(
        cast(MultimodalIngestionService, _FakeIngestion())
    )
    prepared = asyncio.run(sessions.prepare("conversation-1", ()))

    assert prepared == sessions.list("conversation-1")
    assert sessions.context_for("conversation-1", "doc-1", "question") == (
        "context:question"
    )
    asyncio.run(sessions.clear("conversation-1"))
    assert sessions.list("conversation-1") == ()
