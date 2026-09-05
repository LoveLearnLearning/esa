"""HTTP contract tests for the personal knowledge-base management MVP."""

from __future__ import annotations

import asyncio
import io
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from PIL import Image

from backend.core.services.personal_knowledge_base_service import (
    PersonalKnowledgeBaseFileStorage,
    PersonalKnowledgeBaseService,
)
from backend.core.stores.migrations import run_migrations
from backend.core.stores.personal_knowledge_base_store import PersonalKnowledgeBaseStore
from backend.core.stores.session_store import SessionStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal
from backend.core.web.webAPI import create_app
from backend.core.web.routers.personal_knowledge_base import _OpenFileResponse


class _ASGIClient:
    """Thread-free HTTP client for restricted test executors."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        async def send() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url="http://testserver",
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(send())

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def head(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("HEAD", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)


def _client(tmp_path, *, enabled: bool = True) -> tuple[_ASGIClient, dict, dict]:
    database = tmp_path / "user.db"
    UserStore(database)
    SessionStore(database)
    run_migrations(database)
    connection = sqlite3.connect(database)
    connection.executemany(
        "INSERT INTO users (id, username, password_hash) VALUES (?, ?, 'hash')",
        (("user-one", "alice"), ("user-two", "bob")),
    )
    connection.commit()
    connection.close()
    sessions = SessionStore(database)
    now = datetime.now(timezone.utc)
    sessions.create(SessionPrincipal("session-one", "user-one", now, now + timedelta(hours=1)))
    sessions.create(SessionPrincipal("session-two", "user-two", now, now + timedelta(hours=1)))
    store = PersonalKnowledgeBaseStore(database)
    storage = PersonalKnowledgeBaseFileStorage(
        tmp_path / "personal-kb",
        max_file_bytes=1024,
        max_batch_files=20,
        max_batch_bytes=4096,
        max_expanded_bytes=8192,
    )
    service = PersonalKnowledgeBaseService(
        store,
        storage,
        enabled=enabled,
        max_user_bytes=8192,
        max_user_files=10,
    )
    app = create_app(
        app_lifespan=None,
        trusted_hosts=("testserver",),
        forwarded_allow_ips=("testclient",),
        enable_legacy_routes=False,
    )
    app.state.session_store = sessions
    app.state.personal_knowledge_base_service = service
    return (
        _ASGIClient(app),
        {"Authorization": "Bearer session-one"},
        {"Authorization": "Bearer session-two"},
    )


def test_empty_snapshot_and_authentication(tmp_path):
    client, user_one, _user_two = _client(tmp_path)
    assert client.get("/api/me/knowledge-base").status_code == 401
    response = client.get("/api/me/knowledge-base", headers=user_one)
    assert response.status_code == 200
    body = response.json()
    updated_at = body.pop("updated_at")
    assert body == {
        "file_count": 0,
        "chunk_count": 0,
        "index_count": 0,
        "status": "idle",
        "progress": 0.0,
        "error": None,
        "files": [],
    }
    # Resolving the default library creates the durable per-user base, so an
    # empty library still has a meaningful creation/update timestamp.
    assert isinstance(updated_at, str)
    datetime.fromisoformat(updated_at)


def test_upload_deduplicate_isolate_and_delete(tmp_path):
    client, user_one, user_two = _client(tmp_path)
    missing = client.post("/api/me/knowledge-base/files", headers=user_one)
    assert missing.status_code == 422

    uploaded = client.post(
        "/api/me/knowledge-base/files",
        headers=user_one,
        files=[("files", ("notes.txt", b"shortest path", "application/octet-stream"))],
    )
    assert uploaded.status_code == 202
    body = uploaded.json()
    assert body["file_count"] == len(body["files"]) == 1
    assert body["status"] == "queued"
    assert body["files"][0]["media_type"] == "text/plain"
    file_id = body["files"][0]["id"]

    duplicate = client.post(
        "/api/me/knowledge-base/files",
        headers=user_one,
        files=[("files", ("renamed.txt", b"shortest path", "text/plain"))],
    )
    assert duplicate.status_code == 409  # the first durable upload job is still queued

    isolated = client.get("/api/me/knowledge-base", headers=user_two)
    assert isolated.status_code == 200
    assert isolated.json()["files"] == []
    assert client.delete(
        f"/api/me/knowledge-base/files/{file_id}", headers=user_two
    ).status_code == 404
    assert client.delete(
        f"/api/me/knowledge-base/files/{file_id}", headers=user_one
    ).status_code == 204
    # A retained tombstone makes DELETE idempotent until cleanup completes.
    assert client.delete(
        f"/api/me/knowledge-base/files/{file_id}", headers=user_one
    ).status_code == 204
    assert client.get("/api/me/knowledge-base", headers=user_one).json()["files"] == []


def test_content_get_head_range_headers_and_tenant_isolation(tmp_path):
    client, user_one, user_two = _client(tmp_path)
    payload = b"0123456789abcdefghijklmnopqrstuvwxyz"
    uploaded = client.post(
        "/api/me/knowledge-base/files",
        headers=user_one,
        files=[("files", ("space notes.txt", payload, "text/plain"))],
    )
    assert uploaded.status_code == 202
    file_id = uploaded.json()["files"][0]["id"]
    path = f"/api/me/knowledge-base/files/{file_id}/content"

    assert client.get(path).status_code == 401
    assert client.get(path, headers=user_two).status_code == 404
    assert client.head(path, headers=user_two).status_code == 404

    full = client.get(path, headers=user_one)
    assert full.status_code == 200
    assert full.content == payload
    assert full.headers["content-type"].startswith("text/plain")
    assert full.headers["content-length"] == str(len(payload))
    assert full.headers["content-disposition"] == (
        "inline; filename*=UTF-8''space%20notes.txt"
    )
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["cache-control"] == "private, max-age=300"
    assert full.headers["x-content-type-options"] == "nosniff"
    assert full.headers["content-security-policy"] == "sandbox"
    assert full.headers["cross-origin-resource-policy"] == "same-origin"
    assert full.headers["etag"].startswith('"')

    download = client.get(path.replace("/content", "/download"), headers=user_one)
    assert download.status_code == 200
    assert download.content == payload
    assert download.headers["content-disposition"].startswith("attachment;")

    head = client.head(path, headers=user_one)
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == str(len(payload))

    partial = client.get(path, headers={**user_one, "Range": "bytes=5-11"})
    assert partial.status_code == 206
    assert partial.content == payload[5:12]
    assert partial.headers["content-range"] == f"bytes 5-11/{len(payload)}"
    assert partial.headers["content-length"] == "7"

    suffix = client.get(path, headers={**user_one, "Range": "bytes=-4"})
    assert suffix.status_code == 206
    assert suffix.content == payload[-4:]

    range_head = client.head(
        path, headers={**user_one, "Range": "bytes=2-8"}
    )
    assert range_head.status_code == 206
    assert range_head.content == b""
    assert range_head.headers["content-range"] == f"bytes 2-8/{len(payload)}"
    assert range_head.headers["content-length"] == "7"

    stale_if_range = client.get(
        path,
        headers={**user_one, "Range": "bytes=2-8", "If-Range": '"stale"'},
    )
    assert stale_if_range.status_code == 200
    assert stale_if_range.content == payload

    malformed = client.get(path, headers={**user_one, "Range": "items=0-1"})
    assert malformed.status_code == 400
    multiple = client.get(path, headers={**user_one, "Range": "bytes=0-1,3-4"})
    assert multiple.status_code == 400
    outside = client.get(path, headers={**user_one, "Range": "bytes=999-"})
    assert outside.status_code == 416
    assert outside.headers["content-range"] == f"bytes */{len(payload)}"

    assert client.delete(path.removesuffix("/content"), headers=user_one).status_code == 204
    assert client.get(path, headers=user_one).status_code == 404


def test_content_rejects_durable_path_drift(tmp_path):
    client, user_one, _user_two = _client(tmp_path)
    uploaded = client.post(
        "/api/me/knowledge-base/files",
        headers=user_one,
        files=[("files", ("notes.txt", b"trusted", "text/plain"))],
    )
    file_id = uploaded.json()["files"][0]["id"]
    store = client.app.state.personal_knowledge_base_service.store
    store.execute(
        "UPDATE personal_knowledge_base_files SET source_path = ? WHERE file_id = ?",
        (str(tmp_path / "foreign.txt"), file_id),
    )
    (tmp_path / "foreign.txt").write_bytes(b"foreign")

    response = client.get(
        f"/api/me/knowledge-base/files/{file_id}/content", headers=user_one
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "个人知识库持久化失败"}


def test_text_and_image_preview_are_bounded_derived_responses(tmp_path):
    client, user_one, user_two = _client(tmp_path)
    uploaded = client.post(
        "/api/me/knowledge-base/files",
        headers=user_one,
        files=[("files", ("lecture.txt", b"original source", "text/plain"))],
    )
    assert uploaded.status_code == 202
    file_id = uploaded.json()["files"][0]["id"]
    preview_path = f"/api/me/knowledge-base/files/{file_id}/preview"
    assert client.get(preview_path, headers=user_one).status_code == 409

    service = client.app.state.personal_knowledge_base_service
    artifact = service.storage.artifacts_root / file_id / "pipeline"
    artifact.mkdir(parents=True, mode=0o700)
    os.chmod(artifact.parent, 0o700)
    os.chmod(artifact, 0o700)
    chunks = artifact / "chunks.json"
    chunks.write_text("{}", encoding="utf-8")
    preview = artifact / "preview.txt"
    preview.write_bytes(b"bounded extracted preview\n")
    os.chmod(chunks, 0o600)
    os.chmod(preview, 0o600)
    service.store.execute(
        """
        UPDATE personal_knowledge_base_files
        SET chunk_manifest_path = ?, status = 'ready'
        WHERE file_id = ?
        """,
        (str(chunks), file_id),
    )

    assert client.get(preview_path, headers=user_two).status_code == 404
    text_preview = client.get(preview_path, headers=user_one)
    assert text_preview.status_code == 200
    assert text_preview.content == b"bounded extracted preview\n"
    assert text_preview.headers["content-type"].startswith("text/plain")

    service.store.execute(
        """
        UPDATE personal_knowledge_base_files
        SET filename = 'lecture.pdf', suffix = '.pdf', media_type = 'application/pdf'
        WHERE file_id = ?
        """,
        (file_id,),
    )
    pdf_text_preview = client.get(preview_path, headers=user_one)
    assert pdf_text_preview.status_code == 200
    assert pdf_text_preview.content == b"bounded extracted preview\n"
    assert pdf_text_preview.headers["content-type"].startswith("text/plain")

    office_pdf = artifact / "preview.pdf"
    office_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    os.chmod(office_pdf, 0o600)
    service.store.execute(
        """
        UPDATE personal_knowledge_base_files
        SET filename = 'lecture.docx', suffix = '.docx',
            media_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        WHERE file_id = ?
        """,
        (file_id,),
    )
    converted_preview = client.get(preview_path, headers=user_one)
    assert converted_preview.status_code == 200
    assert converted_preview.content.startswith(b"%PDF-")
    assert converted_preview.headers["content-type"] == "application/pdf"

    buffer = io.BytesIO()
    Image.new("RGB", (32, 16), (20, 40, 60)).save(buffer, format="PNG")
    image_upload = client.post(
        "/api/me/knowledge-base/files",
        headers=user_two,
        files=[("files", ("diagram.png", buffer.getvalue(), "image/png"))],
    )
    assert image_upload.status_code == 202
    image_id = image_upload.json()["files"][0]["id"]
    thumbnail = client.get(
        f"/api/me/knowledge-base/files/{image_id}/preview", headers=user_two
    )
    assert thumbnail.status_code == 200, thumbnail.text
    assert thumbnail.headers["content-type"].startswith("image/jpeg")
    with Image.open(io.BytesIO(thumbnail.content)) as rendered:
        assert rendered.size == (32, 16)


def test_large_response_streams_chunks_and_closes_on_cancellation(tmp_path):
    path = tmp_path / "near-limit.bin"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    os.ftruncate(descriptor, 200 * 1024 * 1024 - 1)
    response = _OpenFileResponse(
        descriptor=descriptor,
        filename="near-limit.bin",
        media_type="application/octet-stream",
        size=os.fstat(descriptor).st_size,
        sha256="a" * 64,
        modified_ns=os.fstat(descriptor).st_mtime_ns,
        method="GET",
        range_header=None,
        if_range=None,
    )
    body_sizes: list[int] = []

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            body_sizes.append(len(message["body"]))
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(response({}, None, send))

    assert body_sizes == [64 * 1024]
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_upload_validation_rebuild_and_disabled_feature(tmp_path):
    client, user_one, _user_two = _client(tmp_path)
    empty = client.post(
        "/api/me/knowledge-base/files",
        headers=user_one,
        files=[("files", ("empty.txt", b"", "text/plain"))],
    )
    assert empty.status_code == 400
    unsupported = client.post(
        "/api/me/knowledge-base/files",
        headers=user_one,
        files=[("files", ("archive.exe", b"MZ", "application/octet-stream"))],
    )
    assert unsupported.status_code == 415
    spoofed = client.post(
        "/api/me/knowledge-base/files",
        headers=user_one,
        files=[("files", ("fake.pdf", b"not a pdf", "application/pdf"))],
    )
    assert spoofed.status_code == 400
    assert client.post(
        "/api/me/knowledge-base/rebuild", headers=user_one, json={}
    ).status_code == 400

    disabled, disabled_headers, _ = _client(tmp_path / "disabled", enabled=False)
    assert disabled.get(
        "/api/me/knowledge-base", headers=disabled_headers
    ).status_code == 503


def test_upload_request_size_is_rejected_before_multipart_parsing(tmp_path):
    client, user_one, _user_two = _client(tmp_path)
    response = client.post(
        "/api/me/knowledge-base/files",
        headers={**user_one, "Content-Length": str(2**40)},
        content=b"",
    )
    assert response.status_code == 413

    client.app.state.personal_knowledge_base_service.max_user_bytes = 1
    quota = client.post(
        "/api/me/knowledge-base/files",
        headers=user_one,
        files=[("files", ("quota.txt", b"too large", "text/plain"))],
    )
    assert quota.status_code == 413


def test_named_library_upload_is_rejected_before_multipart_parsing(tmp_path):
    client, user_one, _user_two = _client(tmp_path)
    created = client.post(
        "/api/me/knowledge-base/libraries",
        headers=user_one,
        json={"name": "课程资料"},
    )
    assert created.status_code == 201
    library_id = created.json()["id"]
    response = client.post(
        f"/api/me/knowledge-base/libraries/{library_id}/files",
        headers={**user_one, "Content-Length": str(2**40)},
        content=b"",
    )
    assert response.status_code == 413


def test_rebuild_returns_accepted_snapshot_for_existing_file(tmp_path):
    client, user_one, _user_two = _client(tmp_path)
    uploaded = client.post(
        "/api/me/knowledge-base/files",
        headers=user_one,
        files=[("files", ("notes.txt", b"graph theory", "text/plain"))],
    )
    assert uploaded.status_code == 202
    # This contract test does not run the model pipeline. Settle its queued
    # upload so the independent rebuild endpoint can be exercised.
    store = client.app.state.personal_knowledge_base_service.store
    store.execute(
        """
        UPDATE personal_knowledge_base_jobs
        SET status = 'cancelled', stage = 'cancelled', completed_at = updated_at
        WHERE user_id = 'user-one' AND job_type = 'upload'
        """
    )

    rebuilt = client.post(
        "/api/me/knowledge-base/rebuild", headers=user_one, json={}
    )

    assert rebuilt.status_code == 202
    assert rebuilt.json()["status"] == "queued"
    assert rebuilt.json()["file_count"] == 1
