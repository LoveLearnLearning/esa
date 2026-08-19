# backend/agent/mm/session.py

"""Conversation-scoped handles for prepared multimodal attachments."""

from __future__ import annotations

import asyncio
from pathlib import Path

from backend.agent.rag.retrieval.contracts import ContextLevel, SearchResponse

from .contracts import PreparedAttachment
from .service import MultimodalIngestionService


class MultimodalSessionService:
    """Own attachment handles explicitly by conversation/session identifier."""

    def __init__(self, ingestion: MultimodalIngestionService) -> None:
        """初始化 `MultimodalSessionService` 实例。"""
        self.ingestion = ingestion
        self._sessions: dict[str, dict[str, PreparedAttachment]] = {}
        self._lock = asyncio.Lock()

    async def prepare(
        self, session_id: str, paths: list[Path] | tuple[Path, ...]
    ) -> tuple[PreparedAttachment, ...]:
        """准备 `prepare` 相关数据。

        Args:
            session_id: str => 会话 ID。
            paths: list[Path] | tuple[Path, ...] => `paths` 参数。

        Returns:
            tuple[PreparedAttachment, ...] => 处理结果。
        """
        if not session_id.strip():
            raise ValueError("session_id cannot be blank")
        prepared = await self.ingestion.prepare_files(paths)
        async with self._lock:
            bucket = self._sessions.setdefault(session_id, {})
            for item in prepared:
                bucket[item.document.document_id] = item
        return prepared

    async def prepare_attachment(
        self,
        session_id: str,
        attachment_id: str,
        path: Path,
    ) -> PreparedAttachment:
        """Prepare one persisted upload under its public attachment handle."""

        if not session_id.strip() or not attachment_id.strip():
            raise ValueError("session_id and attachment_id cannot be blank")
        existing = self._sessions.get(session_id, {}).get(attachment_id)
        if existing is not None:
            return existing
        prepared = await self.ingestion.prepare_file(Path(path))
        async with self._lock:
            bucket = self._sessions.setdefault(session_id, {})
            return bucket.setdefault(attachment_id, prepared)

    def list(self, session_id: str) -> tuple[PreparedAttachment, ...]:
        """列出 `list` 相关数据。"""
        return tuple(self._sessions.get(session_id, {}).values())

    async def remove(self, session_id: str, attachment_id: str) -> bool:
        """移除 `remove` 相关数据。

        Args:
            session_id: str => 会话 ID。
            attachment_id: str => 附件 ID。

        Returns:
            bool => 处理结果。
        """
        async with self._lock:
            bucket = self._sessions.get(session_id)
            if bucket is None or attachment_id not in bucket:
                return False
            del bucket[attachment_id]
            if not bucket:
                self._sessions.pop(session_id, None)
            return True

    def context_for(
        self,
        session_id: str,
        attachment_id: str,
        query: str,
        context_level: ContextLevel = ContextLevel.EVIDENCE,
    ) -> str | SearchResponse:
        """处理 `context_for` 相关逻辑。

        Args:
            session_id: str => 会话 ID。
            attachment_id: str => 附件 ID。
            query: str => 查询文本。
            context_level: ContextLevel => `context_level` 参数。

        Returns:
            str | SearchResponse => 处理结果。
        """
        try:
            attachment = self._sessions[session_id][attachment_id]
        except KeyError as exc:
            raise KeyError("attachment is not registered for this session") from exc
        return attachment.context_for(query, context_level)

    async def clear(self, session_id: str) -> None:
        """清空 `clear` 相关数据。"""
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def close(self) -> None:
        """释放当前对象持有的资源。"""
        async with self._lock:
            self._sessions.clear()
