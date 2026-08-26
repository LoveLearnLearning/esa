"""Management service and safe source-file storage for personal knowledge bases."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import time
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Protocol

from backend.core.stores.personal_knowledge_base_store import (
    NewPersonalKnowledgeBaseFile,
    PersonalKnowledgeBaseStore,
)


SUPPORTED_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_POSIX_PERMISSION_CHECKS = os.name == "posix" and hasattr(os, "geteuid")


def _owner_mode_is_private(metadata: os.stat_result) -> bool:
    if not _POSIX_PERMISSION_CHECKS:
        return True
    return metadata.st_uid == os.geteuid() and metadata.st_mode & 0o077 == 0


def _sync_directory(path: Path) -> None:
    """Durably sync a directory where the platform exposes directory fds."""

    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_descriptor_at(descriptor: int, size: int, offset: int) -> bytes:
    pread = getattr(os, "pread", None)
    if pread is not None:
        return pread(descriptor, size, offset)
    os.lseek(descriptor, offset, os.SEEK_SET)
    return os.read(descriptor, size)
_OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")


class PersonalKnowledgeBaseDisabled(RuntimeError):
    """The feature is not enabled in this deployment."""


class InvalidKnowledgeBaseFile(ValueError):
    """The upload is empty, malformed, or inconsistent with its suffix."""


class UnsupportedKnowledgeBaseFile(ValueError):
    """The filename suffix is outside the MVP support matrix."""


class PersonalKnowledgeBaseStorageIntegrityError(OSError):
    """Durable metadata and the private source-file tree disagree."""


class PersonalKnowledgeBasePreviewUnavailable(RuntimeError):
    """A safe derived preview is not ready for the current file revision."""


class PersonalKnowledgeBaseUserPurgerProtocol(Protocol):
    async def purge(self, user_id: str) -> dict[str, Any]: ...


class KnowledgeBaseUploadTooLarge(ValueError):
    """A file or batch exceeded its configured byte limit."""


@dataclass(frozen=True, slots=True)
class UploadSource:
    """Framework-neutral streaming upload input."""

    filename: str
    media_type: str
    read: Callable[[int], Awaitable[bytes]]
    size_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class PersonalKnowledgeBaseContent:
    """An already-open, tenant-authorized original file.

    Keeping the descriptor open closes the check/use gap between authorization
    and streaming.  The HTTP response owns and closes ``file_descriptor``.
    """

    file_descriptor: int
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    modified_ns: int


class PersonalKnowledgeBaseFileStorage:
    """Commit validated sources atomically inside the durable filesystem."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_file_bytes: int,
        max_batch_files: int,
        max_batch_bytes: int,
        max_expanded_bytes: int,
        max_pages: int = 5000,
        max_image_pixels: int = 100_000_000,
        min_free_bytes: int = 0,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.files_root = self.root / "files"
        self.artifacts_root = self.root / "artifacts"
        self.max_file_bytes = max_file_bytes
        self.max_batch_files = max_batch_files
        self.max_batch_bytes = max_batch_bytes
        self.max_expanded_bytes = max_expanded_bytes
        self.max_pages = max_pages
        self.max_image_pixels = max_image_pixels
        self.min_free_bytes = min_free_bytes
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.files_root.mkdir(exist_ok=True, mode=0o700)
        self.artifacts_root.mkdir(exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        os.chmod(self.files_root, 0o700)
        os.chmod(self.artifacts_root, 0o700)
        self.validate_permissions()

    def validate_permissions(self) -> None:
        """Fail closed on foreign-owned, group-visible, or symlinked data."""

        for current_root, directories, files in os.walk(self.root):
            current = Path(current_root)
            if current.is_symlink():
                raise RuntimeError("personal knowledge-base root contains a symlink")
            stat = current.stat()
            if not _owner_mode_is_private(stat):
                raise RuntimeError(
                    "personal knowledge-base directory owner/mode is not private"
                )
            for name in directories:
                if (current / name).is_symlink():
                    raise RuntimeError(
                        "personal knowledge-base root contains a symlink"
                    )
            for name in files:
                path = current / name
                if path.is_symlink():
                    raise RuntimeError(
                        "personal knowledge-base root contains a symlink"
                    )
                file_stat = path.stat()
                if not _owner_mode_is_private(file_stat):
                    raise RuntimeError(
                        "personal knowledge-base file owner/mode is not private"
                    )

    @staticmethod
    def _safe_filename(filename: str) -> str:
        value = Path(filename.replace("\\", "/")).name
        if not value or len(value.encode("utf-8")) > 255:
            raise InvalidKnowledgeBaseFile("文件名无效或过长")
        if _CONTROL_CHARACTERS.search(value):
            raise InvalidKnowledgeBaseFile("文件名包含控制字符")
        return value

    def _directory(self, file_id: str) -> Path:
        # file_id is generated by this service, never supplied by a client.
        uuid.UUID(file_id)
        value = (self.files_root / file_id).resolve()
        value.relative_to(self.files_root)
        return value

    def _validate_zip(self, path: Path, suffix: str) -> None:
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                total = sum(item.file_size for item in infos)
                if len(infos) > 100_000 or total > self.max_expanded_bytes:
                    raise InvalidKnowledgeBaseFile("Office 文件展开后超过资源限制")
                for item in infos:
                    if item.file_size > 0 and item.compress_size == 0:
                        raise InvalidKnowledgeBaseFile("Office 文件压缩结构无效")
                    if item.compress_size and item.file_size / item.compress_size > 1000:
                        raise InvalidKnowledgeBaseFile("Office 文件压缩比超过安全限制")
                names = {item.filename for item in infos}
        except (zipfile.BadZipFile, OSError) as exc:
            raise InvalidKnowledgeBaseFile("Office 文件内容无效") from exc
        prefix = {".docx": "word/", ".pptx": "ppt/", ".xlsx": "xl/"}[suffix]
        if "[Content_Types].xml" not in names or not any(
            name.startswith(prefix) for name in names
        ):
            raise InvalidKnowledgeBaseFile("Office 文件内容与扩展名不匹配")

    def _validate_content(self, path: Path, suffix: str) -> None:
        with path.open("rb") as stream:
            head = stream.read(16)
        if suffix == ".pdf" and not head.startswith(b"%PDF-"):
            raise InvalidKnowledgeBaseFile("PDF 文件内容无效")
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader

                reader = PdfReader(path, strict=False)
                if reader.is_encrypted:
                    raise InvalidKnowledgeBaseFile("不支持加密 PDF")
                if len(reader.pages) > self.max_pages:
                    raise InvalidKnowledgeBaseFile("PDF 页数超过资源限制")
            except InvalidKnowledgeBaseFile:
                raise
            except Exception as exc:
                raise InvalidKnowledgeBaseFile("PDF 文件结构无效") from exc
        if suffix in {".doc", ".ppt", ".xls"} and not head.startswith(_OLE_MAGIC):
            raise InvalidKnowledgeBaseFile("Office 文件内容与扩展名不匹配")
        if suffix in {".docx", ".pptx", ".xlsx"}:
            self._validate_zip(path, suffix)
        if suffix == ".png" and not head.startswith(b"\x89PNG\r\n\x1a\n"):
            raise InvalidKnowledgeBaseFile("PNG 文件内容无效")
        if suffix in {".jpg", ".jpeg"} and not head.startswith(b"\xff\xd8\xff"):
            raise InvalidKnowledgeBaseFile("JPEG 文件内容无效")
        if suffix == ".webp" and not (
            head.startswith(b"RIFF") and head[8:12] == b"WEBP"
        ):
            raise InvalidKnowledgeBaseFile("WebP 文件内容无效")
        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            try:
                from PIL import Image, UnidentifiedImageError

                with Image.open(path) as image:
                    width, height = image.size
                    if width <= 0 or height <= 0:
                        raise InvalidKnowledgeBaseFile("图片尺寸无效")
                    if width * height > self.max_image_pixels:
                        raise InvalidKnowledgeBaseFile("图片像素数超过资源限制")
                    image.verify()
            except InvalidKnowledgeBaseFile:
                raise
            except (OSError, UnidentifiedImageError) as exc:
                raise InvalidKnowledgeBaseFile("图片文件结构无效") from exc
        if suffix in {".txt", ".md", ".csv", ".json"}:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise InvalidKnowledgeBaseFile("文本文件必须使用 UTF-8 编码") from exc
            if "\x00" in text:
                raise InvalidKnowledgeBaseFile("文本文件包含 NUL 字节")
            if suffix == ".json":
                try:
                    json.loads(text)
                except json.JSONDecodeError as exc:
                    raise InvalidKnowledgeBaseFile("JSON 文件内容无效") from exc

    async def save_batch(
        self, uploads: Iterable[UploadSource]
    ) -> list[NewPersonalKnowledgeBaseFile]:
        values = list(uploads)
        declared_total = self.reservation_bytes(values)
        if shutil.disk_usage(self.files_root).free < declared_total + self.min_free_bytes:
            raise KnowledgeBaseUploadTooLarge("个人知识库持久盘安全余量不足")
        committed: list[NewPersonalKnowledgeBaseFile] = []
        created_ids: list[str] = []
        batch_bytes = 0
        try:
            for upload in values:
                filename = self._safe_filename(upload.filename)
                suffix = Path(filename).suffix.lower()
                media_type = SUPPORTED_MEDIA_TYPES.get(suffix)
                if media_type is None:
                    raise UnsupportedKnowledgeBaseFile("文件格式不受支持")
                file_id = str(uuid.uuid4())
                created_ids.append(file_id)
                directory = self._directory(file_id)
                directory.mkdir(mode=0o700)
                temporary_path = directory / ".uploading"
                source_path = directory / f"source{suffix}"
                digest = hashlib.sha256()
                size = 0
                with temporary_path.open("xb") as stream:
                    os.chmod(temporary_path, 0o600)
                    while chunk := await upload.read(1024 * 1024):
                        size += len(chunk)
                        batch_bytes += len(chunk)
                        if size > self.max_file_bytes:
                            raise KnowledgeBaseUploadTooLarge("单文件大小超过限制")
                        if batch_bytes > self.max_batch_bytes:
                            raise KnowledgeBaseUploadTooLarge("单批文件总大小超过限制")
                        if shutil.disk_usage(self.files_root).free < self.min_free_bytes:
                            raise KnowledgeBaseUploadTooLarge(
                                "个人知识库持久盘安全余量不足"
                            )
                        digest.update(chunk)
                        stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                if size == 0:
                    raise InvalidKnowledgeBaseFile("文件为空")
                self._validate_content(temporary_path, suffix)
                os.replace(temporary_path, source_path)
                _sync_directory(directory)
                committed.append(
                    NewPersonalKnowledgeBaseFile(
                        file_id=file_id,
                        filename=filename,
                        suffix=suffix,
                        media_type=media_type,
                        size_bytes=size,
                        sha256=digest.hexdigest(),
                        source_path=str(source_path),
                        uploaded_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
            return committed
        except BaseException:
            # Only remove directories allocated by this batch. Other requests
            # may have their own legitimate .uploading file concurrently.
            for file_id in created_ids:
                shutil.rmtree(self._directory(file_id), ignore_errors=True)
            raise

    def reservation_bytes(self, uploads: Iterable[UploadSource]) -> int:
        """Return a conservative byte reservation before streaming a batch."""

        values = list(uploads)
        if not values:
            raise InvalidKnowledgeBaseFile("没有可用文件")
        if len(values) > self.max_batch_files:
            raise KnowledgeBaseUploadTooLarge("单次上传文件数量超过限制")
        declared_sizes = [item.size_bytes for item in values]
        if any(size is not None and size < 0 for size in declared_sizes):
            raise InvalidKnowledgeBaseFile("文件大小声明无效")
        if any(size == 0 for size in declared_sizes):
            raise InvalidKnowledgeBaseFile("文件为空")
        declared_total = sum(
            size if size is not None else self.max_file_bytes
            for size in declared_sizes
        )
        if declared_total > self.max_batch_bytes:
            raise KnowledgeBaseUploadTooLarge("单批文件总大小超过限制")
        return declared_total

    def discard(self, file_id: str) -> None:
        shutil.rmtree(self._directory(file_id), ignore_errors=True)

    def open_content(self, record: dict[str, Any]) -> PersonalKnowledgeBaseContent:
        """Open a validated source without following a final-component symlink."""

        file_id = str(record["file_id"])
        suffix = str(record["suffix"])
        expected = self._directory(file_id) / f"source{suffix}"
        stored = Path(str(record["source_path"]))
        try:
            if stored.resolve(strict=True) != expected.resolve(strict=True):
                raise PersonalKnowledgeBaseStorageIntegrityError(
                    "personal knowledge-base source path drift"
                )
        except (FileNotFoundError, OSError) as exc:
            raise FileNotFoundError("personal knowledge-base source is missing") from exc
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(expected, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise PersonalKnowledgeBaseStorageIntegrityError(
                    "personal knowledge-base source is not a regular file"
                )
            if not _owner_mode_is_private(metadata):
                raise PersonalKnowledgeBaseStorageIntegrityError(
                    "personal knowledge-base source owner/mode is not private"
                )
            if metadata.st_size != int(record["size_bytes"]):
                raise PersonalKnowledgeBaseStorageIntegrityError(
                    "personal knowledge-base source size drift"
                )
            return PersonalKnowledgeBaseContent(
                file_descriptor=descriptor,
                filename=str(record["filename"]),
                media_type=str(record["media_type"]),
                size_bytes=metadata.st_size,
                sha256=str(record["sha256"]),
                modified_ns=metadata.st_mtime_ns,
            )
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _descriptor_content(
        descriptor: int, *, filename: str, media_type: str
    ) -> PersonalKnowledgeBaseContent:
        metadata = os.fstat(descriptor)
        digest = hashlib.sha256()
        offset = 0
        while offset < metadata.st_size:
            chunk = _read_descriptor_at(
                descriptor,
                min(1024 * 1024, metadata.st_size - offset),
                offset,
            )
            if not chunk:
                raise PersonalKnowledgeBaseStorageIntegrityError(
                    "personal preview artifact truncated"
                )
            digest.update(chunk)
            offset += len(chunk)
        return PersonalKnowledgeBaseContent(
            file_descriptor=descriptor,
            filename=filename,
            media_type=media_type,
            size_bytes=metadata.st_size,
            sha256=digest.hexdigest(),
            modified_ns=metadata.st_mtime_ns,
        )

    def _open_preview_artifact(
        self,
        *,
        file_id: str,
        path: Path,
        filename: str,
        media_type: str,
    ) -> PersonalKnowledgeBaseContent:
        raw_root = self.artifacts_root / file_id
        if raw_root.is_symlink() or path.is_symlink():
            raise PersonalKnowledgeBaseStorageIntegrityError(
                "personal preview artifact path contains a symlink"
            )
        root = raw_root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise PersonalKnowledgeBaseStorageIntegrityError(
                "personal preview artifact path drift"
            ) from exc
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(resolved, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise PersonalKnowledgeBaseStorageIntegrityError(
                    "personal preview artifact is not a regular file"
                )
            if not _owner_mode_is_private(metadata):
                raise PersonalKnowledgeBaseStorageIntegrityError(
                    "personal preview artifact owner/mode is not private"
                )
            return self._descriptor_content(
                descriptor, filename=filename, media_type=media_type
            )
        except BaseException:
            os.close(descriptor)
            raise

    def open_text_preview(
        self, record: dict[str, Any]
    ) -> PersonalKnowledgeBaseContent:
        file_id = str(record["file_id"])
        uuid.UUID(file_id)
        chunk_path_value = record.get("chunk_manifest_path")
        if not chunk_path_value:
            raise PersonalKnowledgeBasePreviewUnavailable("文件预览尚未生成")
        chunk_path = Path(str(chunk_path_value))
        try:
            chunk_path.resolve(strict=True).relative_to(
                (self.artifacts_root / file_id).resolve(strict=True)
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise PersonalKnowledgeBasePreviewUnavailable(
                "文件预览尚未生成"
            ) from exc
        preview_path = chunk_path.with_name("preview.txt")
        office_pdf_path = chunk_path.with_name("preview.pdf")
        try:
            if office_pdf_path.is_file():
                return self._open_preview_artifact(
                    file_id=file_id,
                    path=office_pdf_path,
                    filename=f"{Path(str(record['filename'])).stem}.preview.pdf",
                    media_type="application/pdf",
                )
            return self._open_preview_artifact(
                file_id=file_id,
                path=preview_path,
                filename=f"{record['filename']}.preview.txt",
                media_type="text/plain; charset=utf-8",
            )
        except FileNotFoundError as exc:
            raise PersonalKnowledgeBasePreviewUnavailable(
                "文件预览需要重新构建"
            ) from exc

    def open_image_thumbnail(
        self, record: dict[str, Any]
    ) -> PersonalKnowledgeBaseContent:
        from PIL import Image, ImageOps

        source = self.open_content(record)
        try:
            file_id = str(record["file_id"])
            preview_root = self.artifacts_root / file_id / "preview"
            if preview_root.is_symlink():
                raise PersonalKnowledgeBaseStorageIntegrityError(
                    "personal preview directory is a symlink"
                )
            preview_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(preview_root, 0o700)
            with os.fdopen(os.dup(source.file_descriptor), "rb") as stream:
                with Image.open(stream) as opened:
                    image = ImageOps.exif_transpose(opened)
                    image.thumbnail((1600, 1600))
                    has_alpha = image.mode in {"RGBA", "LA"} or (
                        image.mode == "P" and "transparency" in image.info
                    )
                    extension = ".png" if has_alpha else ".jpg"
                    media_type = "image/png" if has_alpha else "image/jpeg"
                    final_path = preview_root / f"thumbnail-{source.sha256[:24]}{extension}"
                    if not final_path.exists():
                        temporary = preview_root / f".{uuid.uuid4().hex}.partial"
                        try:
                            converted = image.convert("RGBA" if has_alpha else "RGB")
                            converted.save(
                                temporary,
                                format="PNG" if has_alpha else "JPEG",
                                optimize=True,
                                quality=85,
                            )
                            os.chmod(temporary, 0o600)
                            with temporary.open("r+b") as saved:
                                os.fsync(saved.fileno())
                            os.replace(temporary, final_path)
                        finally:
                            if temporary.exists():
                                temporary.unlink()
            return self._open_preview_artifact(
                file_id=file_id,
                path=final_path,
                filename=f"{Path(str(record['filename'])).stem}.preview{extension}",
                media_type=media_type,
            )
        finally:
            os.close(source.file_descriptor)

    def discard_artifacts(self, file_id: str) -> None:
        uuid.UUID(file_id)
        candidate = self.artifacts_root / file_id
        if candidate.is_symlink():
            raise RuntimeError("personal artifact cleanup refused a symlink")
        path = candidate.resolve()
        path.relative_to(self.artifacts_root)
        if path.exists():
            shutil.rmtree(path, ignore_errors=False)
        if path.exists():
            raise RuntimeError("personal artifact cleanup did not complete")

    def cleanup_orphans(
        self, *, retained_file_ids: set[str], retention_seconds: int
    ) -> dict[str, int]:
        """Remove only stale server-generated paths lacking durable ownership."""

        if retention_seconds < 0:
            raise ValueError("orphan retention cannot be negative")
        cutoff = time.time() - retention_seconds
        removed = {"file_directories": 0, "artifact_directories": 0, "partials": 0}
        for root, counter in (
            (self.files_root, "file_directories"),
            (self.artifacts_root, "artifact_directories"),
        ):
            for entry in root.iterdir():
                if entry.is_symlink() or not entry.is_dir():
                    continue
                try:
                    uuid.UUID(entry.name)
                except ValueError:
                    continue
                if entry.name not in retained_file_ids and entry.stat().st_mtime <= cutoff:
                    shutil.rmtree(entry)
                    removed[counter] += 1
                    continue
                if entry.name in retained_file_ids:
                    candidates = sorted(
                        entry.rglob("*"),
                        key=lambda value: len(value.parts),
                        reverse=True,
                    )
                    for candidate in candidates:
                        if not candidate.exists() and not candidate.is_symlink():
                            continue
                        if (
                            candidate.is_symlink()
                            or not candidate.name.endswith((".partial", ".uploading"))
                            or candidate.stat().st_mtime > cutoff
                        ):
                            continue
                        if candidate.is_dir():
                            shutil.rmtree(candidate)
                        else:
                            candidate.unlink()
                        removed["partials"] += 1
        return removed


class PersonalKnowledgeBaseService:
    """Coordinate durable file commits with the SQLite mutation outbox."""

    def __init__(
        self,
        store: PersonalKnowledgeBaseStore,
        storage: PersonalKnowledgeBaseFileStorage | None,
        *,
        enabled: bool,
        max_user_bytes: int,
        max_user_files: int,
        notify_worker: Callable[[], None] | None = None,
        user_purger: PersonalKnowledgeBaseUserPurgerProtocol | None = None,
    ) -> None:
        self.store = store
        self.storage = storage
        self.enabled = enabled
        self.max_user_bytes = max_user_bytes
        self.max_user_files = max_user_files
        self.notify_worker = notify_worker
        self.user_purger = user_purger

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise PersonalKnowledgeBaseDisabled("个人知识库功能未启用")

    def list_knowledge_bases(self, user_id: str) -> list[dict[str, Any]]:
        self._require_enabled()
        return self.store.list_knowledge_bases(user_id)

    def create_knowledge_base(self, user_id: str, name: str) -> dict[str, Any]:
        self._require_enabled()
        return self.store.create_knowledge_base(user_id=user_id, name=name)

    def resolve_knowledge_base_id(
        self,
        user_id: str,
        knowledge_base_id: str | None,
    ) -> str:
        self._require_enabled()
        return self.store.resolve_knowledge_base_id(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
        )

    def snapshot(
        self,
        user_id: str,
        knowledge_base_id: str | None = None,
    ) -> dict:
        self._require_enabled()
        return self.store.get_snapshot(user_id, knowledge_base_id)

    def open_content(
        self, user_id: str, file_id: str
    ) -> PersonalKnowledgeBaseContent | None:
        self._require_enabled()
        if self.storage is None:
            raise PersonalKnowledgeBaseDisabled("个人知识库文件存储未初始化")
        record = self.store.get_live_file(user_id=user_id, file_id=file_id)
        if record is None:
            return None
        return self.storage.open_content(record)

    def open_preview(
        self, user_id: str, file_id: str
    ) -> PersonalKnowledgeBaseContent | None:
        self._require_enabled()
        if self.storage is None:
            raise PersonalKnowledgeBaseDisabled("个人知识库文件存储未初始化")
        record = self.store.get_live_file(user_id=user_id, file_id=file_id)
        if record is None:
            return None
        if str(record["media_type"]).startswith("image/"):
            return self.storage.open_image_thumbnail(record)
        return self.storage.open_text_preview(record)

    async def upload(
        self,
        user_id: str,
        uploads: Iterable[UploadSource],
        knowledge_base_id: str | None = None,
    ) -> dict:
        self._require_enabled()
        if self.storage is None:
            raise PersonalKnowledgeBaseDisabled("个人知识库文件存储未初始化")
        resolved_knowledge_base_id = self.store.resolve_knowledge_base_id(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
        )
        values = list(uploads)
        reserved_bytes = self.storage.reservation_bytes(values)
        reservation_id = self.store.reserve_upload_capacity(
            user_id=user_id,
            reserved_files=len(values),
            reserved_bytes=reserved_bytes,
            max_user_bytes=self.max_user_bytes,
            max_user_files=self.max_user_files,
        )
        committed: list[NewPersonalKnowledgeBaseFile] = []
        try:
            committed = await self.storage.save_batch(values)
            resolved_ids, job_id = self.store.create_upload(
                user_id=user_id,
                knowledge_base_id=resolved_knowledge_base_id,
                files=committed,
                max_user_bytes=self.max_user_bytes,
                max_user_files=self.max_user_files,
                reservation_id=reservation_id,
            )
        except BaseException:
            for item in committed:
                self.storage.discard(item.file_id)
            raise
        finally:
            self.store.release_upload_reservation(
                user_id=user_id, reservation_id=reservation_id
            )
        retained_ids = set(resolved_ids)
        for item in committed:
            if item.file_id not in retained_ids:
                self.storage.discard(item.file_id)
        if job_id is not None and self.notify_worker is not None:
            self.notify_worker()
        return self.store.get_snapshot(user_id, resolved_knowledge_base_id)

    def delete(self, user_id: str, file_id: str) -> bool:
        self._require_enabled()
        deleted = self.store.tombstone_file(user_id=user_id, file_id=file_id)
        if deleted and self.notify_worker is not None:
            self.notify_worker()
        return deleted

    def rebuild(
        self,
        user_id: str,
        knowledge_base_id: str | None = None,
    ) -> dict | None:
        self._require_enabled()
        resolved_knowledge_base_id = self.store.resolve_knowledge_base_id(
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
        )
        rebuild_scope = (
            resolved_knowledge_base_id if knowledge_base_id is not None else None
        )
        if self.store.queue_rebuild(user_id, rebuild_scope) is None:
            return None
        if self.notify_worker is not None:
            self.notify_worker()
        return self.store.get_snapshot(user_id, knowledge_base_id)

    async def purge_user(self, user_id: str) -> dict[str, Any]:
        """Administrative hook that must run before deleting the main user row."""

        self._require_enabled()
        if self.user_purger is None:
            raise PersonalKnowledgeBaseDisabled(
                "个人知识库用户清理器未初始化"
            )
        return await self.user_purger.purge(user_id)
