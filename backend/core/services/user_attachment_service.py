# backend/core/services/user_attachment_service.py

"""Durable, ownership-scoped storage for user chat attachments."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class AttachmentTooLarge(ValueError):
    """表示 `AttachmentTooLarge` 异常。"""
    pass


@dataclass(frozen=True, slots=True)
class StoredAttachment:
    """封装 `StoredAttachment` 的状态与行为。"""
    attachment_id: str
    user_id: str
    conversation_id: str
    filename: str
    media_type: str
    suffix: str
    size_bytes: int
    sha256: str
    uploaded_at: str
    path: str

    @property
    def source_path(self) -> Path:
        """处理 `source_path` 相关逻辑。"""
        return Path(self.path)


class UserAttachmentStore:
    """Store source files without parsing them during the upload request."""

    def __init__(self, root: str | Path, *, max_bytes: int) -> None:
        """初始化 `UserAttachmentStore` 实例。"""
        self.root = Path(root).expanduser().resolve()
        self.max_bytes = max_bytes
        if max_bytes <= 0:
            raise ValueError("attachment max_bytes must be positive")
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _component(value: str, label: str) -> str:
        """处理 `_component` 相关逻辑。"""
        if not _SAFE_COMPONENT.fullmatch(value):
            raise ValueError(f"invalid {label}")
        return value

    def _directory(
        self,
        user_id: str,
        conversation_id: str,
        attachment_id: str | None = None,
    ) -> Path:
        """处理 `_directory` 相关逻辑。"""
        parts = [
            self._component(user_id, "user_id"),
            self._component(conversation_id, "conversation_id"),
        ]
        if attachment_id is not None:
            parts.append(self._component(attachment_id, "attachment_id"))
        directory = self.root.joinpath(*parts).resolve()
        directory.relative_to(self.root)
        return directory

    async def save(
        self,
        *,
        user_id: str,
        conversation_id: str,
        filename: str,
        media_type: str,
        read: Callable[[int], Awaitable[bytes]],
    ) -> StoredAttachment:
        """保存 `save` 相关数据。

        Args:
            user_id: str => 用户 ID。
            conversation_id: str => 对话 ID。
            filename: str => 文件名。
            media_type: str => `media_type` 参数。
            read: Callable[[int], Awaitable[bytes]] => `read` 参数。

        Returns:
            StoredAttachment => 处理结果。
        """
        safe_name = Path(filename.replace("\\", "/")).name or "attachment"
        attachment_id = str(uuid.uuid4())
        directory = self._directory(user_id, conversation_id, attachment_id)
        directory.mkdir(parents=True, exist_ok=False)
        suffix = Path(safe_name).suffix.lower()
        source_path = directory / f"source{suffix}"
        temporary_path = directory / ".uploading"
        digest = hashlib.sha256()
        size = 0
        try:
            with temporary_path.open("xb") as stream:
                while chunk := await read(1024 * 1024):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise AttachmentTooLarge(
                            f"文件不能超过 {self.max_bytes // (1024 * 1024)} MB"
                        )
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if size == 0:
                raise ValueError("文件为空")
            os.replace(temporary_path, source_path)
            item = StoredAttachment(
                attachment_id=attachment_id,
                user_id=user_id,
                conversation_id=conversation_id,
                filename=safe_name,
                media_type=media_type or "application/octet-stream",
                suffix=suffix,
                size_bytes=size,
                sha256=digest.hexdigest(),
                uploaded_at=datetime.now(timezone.utc).isoformat(),
                path=str(source_path),
            )
            metadata_path = directory / "metadata.json"
            temporary_metadata = directory / ".metadata.json.tmp"
            temporary_metadata.write_text(
                json.dumps(asdict(item), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary_metadata, metadata_path)
            return item
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    def get(
        self,
        *,
        user_id: str,
        conversation_id: str,
        attachment_id: str,
    ) -> StoredAttachment | None:
        """获取 `get` 相关数据。

        Args:
            user_id: str => 用户 ID。
            conversation_id: str => 对话 ID。
            attachment_id: str => 附件 ID。

        Returns:
            StoredAttachment | None => 处理结果。
        """
        directory = self._directory(user_id, conversation_id, attachment_id)
        metadata_path = directory / "metadata.json"
        try:
            value = json.loads(metadata_path.read_text(encoding="utf-8"))
            item = StoredAttachment(**value)
            source = item.source_path.resolve(strict=True)
            source.relative_to(directory)
            if (
                item.user_id != user_id
                or item.conversation_id != conversation_id
                or item.attachment_id != attachment_id
            ):
                return None
            return item
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def require_many(
        self,
        *,
        user_id: str,
        conversation_id: str,
        attachment_ids: list[str],
    ) -> tuple[StoredAttachment, ...]:
        """处理 `require_many` 相关逻辑。

        Args:
            user_id: str => 用户 ID。
            conversation_id: str => 对话 ID。
            attachment_ids: list[str] => `attachment_ids` 参数。

        Returns:
            tuple[StoredAttachment, ...] => 处理结果。
        """
        items = []
        for attachment_id in dict.fromkeys(attachment_ids):
            item = self.get(
                user_id=user_id,
                conversation_id=conversation_id,
                attachment_id=attachment_id,
            )
            if item is None:
                raise KeyError(attachment_id)
            items.append(item)
        return tuple(items)

    def list_for_conversation(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> tuple[StoredAttachment, ...]:
        """Return every valid attachment still stored for one conversation."""
        directory = self._directory(user_id, conversation_id)
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError:
            return ()

        items: list[StoredAttachment] = []
        for child in children:
            if not child.is_dir():
                continue
            item = self.get(
                user_id=user_id,
                conversation_id=conversation_id,
                attachment_id=child.name,
            )
            if item is not None:
                items.append(item)
        return tuple(items)

    def delete(
        self,
        *,
        user_id: str,
        conversation_id: str,
        attachment_id: str,
    ) -> bool:
        """删除 `delete` 相关数据。

        Args:
            user_id: str => 用户 ID。
            conversation_id: str => 对话 ID。
            attachment_id: str => 附件 ID。

        Returns:
            bool => 处理结果。
        """
        directory = self._directory(user_id, conversation_id, attachment_id)
        if not directory.is_dir():
            return False
        shutil.rmtree(directory)
        return True

    def delete_conversation(self, *, user_id: str, conversation_id: str) -> None:
        """删除 `conversation` 相关数据。

        Args:
            user_id: str => 用户 ID。
            conversation_id: str => 对话 ID。
        """
        directory = self._directory(user_id, conversation_id)
        if directory.is_dir():
            shutil.rmtree(directory)
