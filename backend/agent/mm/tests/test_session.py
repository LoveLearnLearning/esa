# backend/agent/mm/tests/test_session.py

"""验证 `session` 相关行为与回归场景。"""

from __future__ import annotations

import asyncio
from pathlib import Path
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

    async def prepare_file(self, _path: object) -> PreparedAttachment:
        """提供文件级准备实现，覆盖后台任务状态机。"""
        await asyncio.sleep(0)
        attachment = SimpleNamespace(
            document=SimpleNamespace(
                document_id="doc-2",
                assets=(SimpleNamespace(kind=SimpleNamespace(value="figure")),),
                source_page_count=2,
                parsed_page_count=2,
                elements=(object(), object()),
                quality_issues=(),
            ),
            mode=SimpleNamespace(value="direct"),
            token_count=7,
        )
        return cast(PreparedAttachment, attachment)


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


def test_multimodal_session_deduplicates_background_prepare() -> None:
    """显式 prepare 与 QAgent 懒解析共享同一任务。"""
    ingestion = _FakeIngestion()
    sessions = MultimodalSessionService(
        cast(MultimodalIngestionService, ingestion)
    )

    async def run() -> None:
        sessions.register_stored("conversation-1", "attachment-1")
        status = await sessions.start_prepare(
            "conversation-1", "attachment-1", Path("/tmp/source.pdf")
        )
        assert status.state in {"parsing", "ready"}
        first, second = await asyncio.gather(
            sessions.prepare_attachment(
                "conversation-1", "attachment-1", Path("/tmp/source.pdf")
            ),
            sessions.prepare_attachment(
                "conversation-1", "attachment-1", Path("/tmp/source.pdf")
            ),
        )
        assert first is second
        ready = sessions.status("conversation-1", "attachment-1")
        assert ready.state == "ready"
        assert ready.document_id == "doc-2"
        assert ready.visual_asset_count == 1

    asyncio.run(run())
