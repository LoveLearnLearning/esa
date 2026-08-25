"""Authenticated personal knowledge-base management endpoints."""

from __future__ import annotations

import sqlite3
import os
from email.utils import formatdate
from typing import Annotated, Literal
from urllib.parse import quote

import anyio.to_thread
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from backend.core.services.personal_knowledge_base_service import (
    InvalidKnowledgeBaseFile,
    KnowledgeBaseUploadTooLarge,
    PersonalKnowledgeBaseDisabled,
    PersonalKnowledgeBasePreviewUnavailable,
    PersonalKnowledgeBaseService,
    UnsupportedKnowledgeBaseFile,
    UploadSource,
)
from backend.core.stores.personal_knowledge_base_store import (
    PersonalKnowledgeBaseConflict,
    PersonalKnowledgeBaseNotFound,
    PersonalKnowledgeBaseQuotaExceeded,
)
from backend.core.utils.models import SessionPrincipal
from backend.core.web.deps import get_current_session


router = APIRouter(prefix="/me/knowledge-base", tags=["personal knowledge base"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]
ResourceStatus = Literal["idle", "queued", "building", "ready", "failed"]
_STREAM_CHUNK_BYTES = 64 * 1024


def _read_at(descriptor: int, size: int, offset: int) -> bytes:
    pread = getattr(os, "pread", None)
    if pread is not None:
        return pread(descriptor, size, offset)
    os.lseek(descriptor, offset, os.SEEK_SET)
    return os.read(descriptor, size)


class KnowledgeBaseFileResponse(BaseModel):
    id: str
    filename: str
    media_type: str
    size_bytes: int
    status: ResourceStatus
    progress: float = Field(ge=0.0, le=1.0)
    chunk_count: int = Field(ge=0)
    index_count: int = Field(ge=0)
    uploaded_at: str
    error: str | None


class PersonalKnowledgeBaseResponse(BaseModel):
    file_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    index_count: int = Field(ge=0)
    status: ResourceStatus
    progress: float = Field(ge=0.0, le=1.0)
    updated_at: str | None
    error: str | None
    files: list[KnowledgeBaseFileResponse]


class KnowledgeBaseSummaryResponse(BaseModel):
    id: str
    name: str
    file_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    index_count: int = Field(ge=0)
    updated_at: str


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _service(request: Request) -> PersonalKnowledgeBaseService:
    return request.app.state.personal_knowledge_base_service


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PersonalKnowledgeBaseDisabled):
        return HTTPException(503, str(exc))
    if isinstance(exc, PersonalKnowledgeBaseNotFound):
        return HTTPException(404, "个人知识库不存在")
    if isinstance(exc, PersonalKnowledgeBaseConflict):
        if str(exc) == "知识库名称已存在":
            return HTTPException(409, str(exc))
        return HTTPException(409, "同一知识库已有上传或重建任务")
    if isinstance(exc, PersonalKnowledgeBasePreviewUnavailable):
        return HTTPException(409, str(exc))
    if isinstance(exc, (KnowledgeBaseUploadTooLarge, PersonalKnowledgeBaseQuotaExceeded)):
        return HTTPException(413, str(exc))
    if isinstance(exc, UnsupportedKnowledgeBaseFile):
        return HTTPException(415, str(exc))
    if isinstance(exc, InvalidKnowledgeBaseFile):
        return HTTPException(400, str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(422, str(exc))
    # Do not expose durable paths or database diagnostics in HTTP responses.
    if isinstance(exc, (OSError, sqlite3.Error)):
        return HTTPException(500, "个人知识库持久化失败")
    raise exc


def _parse_single_range(value: str, size: int) -> tuple[int, int]:
    """Parse one RFC 9110 byte range and return an inclusive interval."""

    try:
        unit, spec = value.split("=", 1)
    except ValueError as exc:
        raise HTTPException(400, "Range 请求格式无效") from exc
    if unit.strip().lower() != "bytes" or "," in spec or "-" not in spec:
        raise HTTPException(400, "仅支持单段 bytes Range")
    start_text, end_text = (part.strip() for part in spec.split("-", 1))
    try:
        if start_text:
            start = int(start_text)
            end = min(int(end_text), size - 1) if end_text else size - 1
        else:
            suffix = int(end_text)
            if suffix <= 0:
                raise ValueError
            start = max(size - suffix, 0)
            end = size - 1
    except ValueError as exc:
        raise HTTPException(400, "Range 请求格式无效") from exc
    if start < 0 or start >= size or end < start:
        raise HTTPException(
            416,
            "Range 超出文件范围",
            headers={"Content-Range": f"bytes */{size}"},
        )
    return start, end


class _OpenFileResponse(Response):
    """Stream a pre-authorized descriptor and close it on every exit path."""

    media_type = None

    def __init__(
        self,
        *,
        descriptor: int,
        filename: str,
        media_type: str,
        size: int,
        sha256: str,
        modified_ns: int,
        method: str,
        range_header: str | None,
        if_range: str | None,
        disposition_type: Literal["inline", "attachment"] = "inline",
    ) -> None:
        self.descriptor = descriptor
        self.start = 0
        self.end = size - 1
        etag = f'"{sha256}"'
        last_modified = formatdate(modified_ns / 1_000_000_000, usegmt=True)
        status_code = 200
        if range_header and (if_range is None or if_range in {etag, last_modified}):
            self.start, self.end = _parse_single_range(range_header, size)
            status_code = 206
        length = self.end - self.start + 1
        disposition_name = quote(filename, safe="")
        headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": (
                f"{disposition_type}; filename*=UTF-8''{disposition_name}"
            ),
            "Content-Length": str(length),
            "Content-Security-Policy": "sandbox",
            "Cross-Origin-Resource-Policy": "same-origin",
            "ETag": etag,
            "Last-Modified": last_modified,
            "X-Content-Type-Options": "nosniff",
        }
        if status_code == 206:
            headers["Content-Range"] = f"bytes {self.start}-{self.end}/{size}"
        super().__init__(
            content=b"",
            status_code=status_code,
            headers=headers,
            media_type=media_type,
        )
        self._head_only = method.upper() == "HEAD"

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        try:
            await send(
                {
                    "type": "http.response.start",
                    "status": self.status_code,
                    "headers": self.raw_headers,
                }
            )
            if self._head_only:
                await send({"type": "http.response.body", "body": b""})
                return
            offset = self.start
            while offset <= self.end:
                chunk = await anyio.to_thread.run_sync(
                    _read_at,
                    self.descriptor,
                    min(_STREAM_CHUNK_BYTES, self.end - offset + 1),
                    offset,
                )
                if not chunk:
                    raise RuntimeError("personal knowledge-base source truncated")
                offset += len(chunk)
                await send(
                    {
                        "type": "http.response.body",
                        "body": chunk,
                        "more_body": offset <= self.end,
                    }
                )
        finally:
            os.close(self.descriptor)


@router.get("", response_model=PersonalKnowledgeBaseResponse)
def get_personal_knowledge_base(
    request: Request,
    session: CurrentSession,
) -> dict:
    try:
        return _service(request).snapshot(session.user_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/libraries", response_model=list[KnowledgeBaseSummaryResponse])
def list_personal_knowledge_bases(
    request: Request,
    session: CurrentSession,
) -> list[dict]:
    try:
        return _service(request).list_knowledge_bases(session.user_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/libraries",
    status_code=201,
    response_model=KnowledgeBaseSummaryResponse,
)
def create_personal_knowledge_base(
    body: KnowledgeBaseCreateRequest,
    request: Request,
    session: CurrentSession,
) -> dict:
    try:
        return _service(request).create_knowledge_base(session.user_id, body.name)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/libraries/{knowledge_base_id}",
    response_model=PersonalKnowledgeBaseResponse,
)
def get_named_personal_knowledge_base(
    knowledge_base_id: str,
    request: Request,
    session: CurrentSession,
) -> dict:
    try:
        return _service(request).snapshot(session.user_id, knowledge_base_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/files", status_code=202, response_model=PersonalKnowledgeBaseResponse)
async def upload_personal_knowledge_base_files(
    request: Request,
    session: CurrentSession,
    files: Annotated[list[UploadFile], File(...)],
) -> dict:
    sources = [
        UploadSource(
            filename=item.filename or "",
            media_type=item.content_type or "application/octet-stream",
            read=item.read,
            size_bytes=item.size,
        )
        for item in files
    ]
    try:
        return await _service(request).upload(session.user_id, sources)
    except Exception as exc:
        raise _http_error(exc) from exc
    finally:
        for item in files:
            await item.close()


@router.post(
    "/libraries/{knowledge_base_id}/files",
    status_code=202,
    response_model=PersonalKnowledgeBaseResponse,
)
async def upload_named_personal_knowledge_base_files(
    knowledge_base_id: str,
    request: Request,
    session: CurrentSession,
    files: Annotated[list[UploadFile], File(...)],
) -> dict:
    sources = [
        UploadSource(
            filename=item.filename or "",
            media_type=item.content_type or "application/octet-stream",
            read=item.read,
            size_bytes=item.size,
        )
        for item in files
    ]
    try:
        return await _service(request).upload(
            session.user_id,
            sources,
            knowledge_base_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    finally:
        for item in files:
            await item.close()


@router.get(
    "/files/{file_id}/download",
    operation_id="download_personal_knowledge_base_file",
)
@router.head("/files/{file_id}/download", include_in_schema=False)
@router.get(
    "/files/{file_id}/content",
    operation_id="get_personal_knowledge_base_file_content",
)
@router.head("/files/{file_id}/content", include_in_schema=False)
def get_personal_knowledge_base_file_content(
    file_id: str,
    request: Request,
    session: CurrentSession,
) -> Response:
    try:
        content = _service(request).open_content(session.user_id, file_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    if content is None:
        raise HTTPException(404, "文件不存在")
    try:
        return _OpenFileResponse(
            descriptor=content.file_descriptor,
            filename=content.filename,
            media_type=content.media_type,
            size=content.size_bytes,
            sha256=content.sha256,
            modified_ns=content.modified_ns,
            method=request.method,
            range_header=request.headers.get("range"),
            if_range=request.headers.get("if-range"),
            disposition_type=(
                "attachment" if request.url.path.endswith("/download") else "inline"
            ),
        )
    except BaseException:
        os.close(content.file_descriptor)
        raise


@router.get(
    "/files/{file_id}/preview",
    operation_id="get_personal_knowledge_base_file_preview",
)
@router.head("/files/{file_id}/preview", include_in_schema=False)
def get_personal_knowledge_base_file_preview(
    file_id: str,
    request: Request,
    session: CurrentSession,
) -> Response:
    try:
        content = _service(request).open_preview(session.user_id, file_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    if content is None:
        raise HTTPException(404, "文件不存在")
    try:
        return _OpenFileResponse(
            descriptor=content.file_descriptor,
            filename=content.filename,
            media_type=content.media_type,
            size=content.size_bytes,
            sha256=content.sha256,
            modified_ns=content.modified_ns,
            method=request.method,
            range_header=request.headers.get("range"),
            if_range=request.headers.get("if-range"),
        )
    except BaseException:
        os.close(content.file_descriptor)
        raise


@router.delete("/files/{file_id}", status_code=204)
def delete_personal_knowledge_base_file(
    file_id: str,
    request: Request,
    session: CurrentSession,
) -> Response:
    try:
        deleted = _service(request).delete(session.user_id, file_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    if not deleted:
        raise HTTPException(404, "文件不存在")
    return Response(status_code=204)


@router.post("/rebuild", status_code=202, response_model=PersonalKnowledgeBaseResponse)
def rebuild_personal_knowledge_base(
    request: Request,
    session: CurrentSession,
) -> dict:
    try:
        snapshot = _service(request).rebuild(session.user_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    if snapshot is None:
        raise HTTPException(400, "空知识库不能重建")
    return snapshot


@router.post(
    "/libraries/{knowledge_base_id}/rebuild",
    status_code=202,
    response_model=PersonalKnowledgeBaseResponse,
)
def rebuild_named_personal_knowledge_base(
    knowledge_base_id: str,
    request: Request,
    session: CurrentSession,
) -> dict:
    try:
        snapshot = _service(request).rebuild(session.user_id, knowledge_base_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    if snapshot is None:
        raise HTTPException(400, "空知识库不能重建")
    return snapshot
