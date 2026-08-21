# backend/agent/mm/session.py

"""Conversation-scoped handles for prepared multimodal attachments."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from backend.agent.rag.retrieval.contracts import ContextLevel, SearchResponse

from .contracts import PreparedAttachment
from .service import MultimodalIngestionService


@dataclass(frozen=True)
class AttachmentPreparationStatus:
    """一个附件在 MM 文件级管线中的可观察状态。"""

    attachment_id: str
    state: str = "stored"
    document_id: str | None = None
    mode: str | None = None
    token_count: int = 0
    page_count: int = 0
    element_count: int = 0
    visual_asset_count: int = 0
    quality_issue_count: int = 0
    error: str | None = None


class MultimodalSessionService:
    """Own attachment handles explicitly by conversation/session identifier."""

    def __init__(self, ingestion: MultimodalIngestionService) -> None:
        """初始化 `MultimodalSessionService` 实例。"""
        self.ingestion = ingestion
        self._sessions: dict[str, dict[str, PreparedAttachment]] = {}
        self._statuses: dict[str, dict[str, AttachmentPreparationStatus]] = {}
        self._tasks: dict[tuple[str, str], asyncio.Task[PreparedAttachment]] = {}
        self._lock = asyncio.Lock()

    def register_stored(self, session_id: str, attachment_id: str) -> None:
        """登记已上传但尚未开始解析的附件。"""
        if not session_id.strip() or not attachment_id.strip():
            raise ValueError("session_id and attachment_id cannot be blank")
        bucket = self._statuses.setdefault(session_id, {})
        bucket.setdefault(
            attachment_id,
            AttachmentPreparationStatus(attachment_id=attachment_id),
        )

    def status(
        self,
        session_id: str,
        attachment_id: str,
        *,
        default_state: str = "stored",
    ) -> AttachmentPreparationStatus:
        """返回附件当前状态；未登记附件按 stored 处理。"""
        return self._statuses.get(session_id, {}).get(
            attachment_id,
            AttachmentPreparationStatus(
                attachment_id=attachment_id,
                state=default_state,
            ),
        )

    def statuses(
        self, session_id: str, attachment_ids: tuple[str, ...] | list[str]
    ) -> tuple[AttachmentPreparationStatus, ...]:
        """按调用方给定的顺序返回多个附件状态。"""
        return tuple(self.status(session_id, item) for item in attachment_ids)

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
        task = await self._ensure_task(session_id, attachment_id, Path(path))
        return await task

    async def start_prepare(
        self,
        session_id: str,
        attachment_id: str,
        path: Path,
    ) -> AttachmentPreparationStatus:
        """启动幂等后台准备任务，不等待 MinerU/VLM 完成。"""
        await self._ensure_task(session_id, attachment_id, Path(path))
        return self.status(session_id, attachment_id)

    async def _ensure_task(
        self, session_id: str, attachment_id: str, path: Path
    ) -> asyncio.Task[PreparedAttachment]:
        key = (session_id, attachment_id)
        async with self._lock:
            existing = self._sessions.get(session_id, {}).get(attachment_id)
            if existing is not None:
                completed = asyncio.get_running_loop().create_future()
                completed.set_result(existing)
                return completed  # type: ignore[return-value]
            task = self._tasks.get(key)
            if task is None:
                self._set_status(
                    session_id,
                    attachment_id,
                    AttachmentPreparationStatus(
                        attachment_id=attachment_id,
                        state="parsing",
                    ),
                )
                task = asyncio.create_task(
                    self._run_prepare(session_id, attachment_id, path),
                    name=f"mm-prepare:{session_id}:{attachment_id}",
                )
                task.add_done_callback(self._consume_task_exception)
                self._tasks[key] = task
            return task

    async def _run_prepare(
        self, session_id: str, attachment_id: str, path: Path
    ) -> PreparedAttachment:
        key = (session_id, attachment_id)
        try:
            prepared = await self.ingestion.prepare_file(path)
            document = prepared.document
            visual_asset_count = sum(
                1
                for asset in document.assets
                if getattr(asset.kind, "value", asset.kind) in {"figure", "table"}
            )
            self._set_status(
                session_id,
                attachment_id,
                AttachmentPreparationStatus(
                    attachment_id=attachment_id,
                    state="ready",
                    document_id=document.document_id,
                    mode=prepared.mode.value,
                    token_count=prepared.token_count,
                    page_count=document.source_page_count or document.parsed_page_count,
                    element_count=len(document.elements),
                    visual_asset_count=visual_asset_count,
                    quality_issue_count=len(document.quality_issues),
                ),
            )
            async with self._lock:
                bucket = self._sessions.setdefault(session_id, {})
                return bucket.setdefault(attachment_id, prepared)
        except Exception as exc:
            self._set_status(
                session_id,
                attachment_id,
                AttachmentPreparationStatus(
                    attachment_id=attachment_id,
                    state="failed",
                    error=f"{type(exc).__name__}: {exc}",
                ),
            )
            raise
        finally:
            async with self._lock:
                self._tasks.pop(key, None)

    @staticmethod
    def _consume_task_exception(task: asyncio.Task[PreparedAttachment]) -> None:
        """消费后台任务异常，避免 create_task 产生未检索异常告警。"""
        if not task.cancelled():
            task.exception()

    def _set_status(
        self,
        session_id: str,
        attachment_id: str,
        value: AttachmentPreparationStatus,
    ) -> None:
        self._statuses.setdefault(session_id, {})[attachment_id] = value

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
            task = self._tasks.pop((session_id, attachment_id), None)
            had_status = attachment_id in self._statuses.get(session_id, {})
            if (
                task is None
                and (bucket is None or attachment_id not in bucket)
                and not had_status
            ):
                return False
            if task is not None:
                task.cancel()
            if bucket is not None and attachment_id in bucket:
                del bucket[attachment_id]
                if not bucket:
                    self._sessions.pop(session_id, None)
            self._statuses.get(session_id, {}).pop(attachment_id, None)
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
            self._statuses.pop(session_id, None)
            for key, task in tuple(self._tasks.items()):
                if key[0] == session_id:
                    task.cancel()
                    self._tasks.pop(key, None)

    async def close(self) -> None:
        """释放当前对象持有的资源。"""
        async with self._lock:
            self._sessions.clear()
            self._statuses.clear()
            for task in self._tasks.values():
                task.cancel()
            self._tasks.clear()
