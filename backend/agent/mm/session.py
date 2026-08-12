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
        self.ingestion = ingestion
        self._sessions: dict[str, dict[str, PreparedAttachment]] = {}
        self._lock = asyncio.Lock()

    async def prepare(
        self, session_id: str, paths: list[Path] | tuple[Path, ...]
    ) -> tuple[PreparedAttachment, ...]:
        if not session_id.strip():
            raise ValueError("session_id cannot be blank")
        prepared = await self.ingestion.prepare_files(paths)
        async with self._lock:
            bucket = self._sessions.setdefault(session_id, {})
            for item in prepared:
                bucket[item.document.document_id] = item
        return prepared

    def list(self, session_id: str) -> tuple[PreparedAttachment, ...]:
        return tuple(self._sessions.get(session_id, {}).values())

    async def remove(self, session_id: str, attachment_id: str) -> bool:
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
        try:
            attachment = self._sessions[session_id][attachment_id]
        except KeyError as exc:
            raise KeyError("attachment is not registered for this session") from exc
        return attachment.context_for(query, context_level)

    async def clear(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def close(self) -> None:
        async with self._lock:
            self._sessions.clear()
