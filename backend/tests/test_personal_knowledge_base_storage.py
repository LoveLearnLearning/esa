from __future__ import annotations

import asyncio
import io
import os
import uuid
import zipfile
from pathlib import Path
from collections import namedtuple
import re

import pytest

from backend.core.services.personal_knowledge_base_service import (
    InvalidKnowledgeBaseFile,
    KnowledgeBaseUploadTooLarge,
    PersonalKnowledgeBaseFileStorage,
    PersonalKnowledgeBaseStorageIntegrityError,
    SUPPORTED_MEDIA_TYPES,
    UploadSource,
)
from backend.core.utils.config import (
    validate_durable_path,
    validate_private_storage_capacity,
)


def _upload(filename: str, content: bytes, media_type: str) -> UploadSource:
    remaining = bytearray(content)

    async def read(_size: int) -> bytes:
        value = bytes(remaining)
        remaining.clear()
        return value

    return UploadSource(filename, media_type, read, len(content))


def _ooxml(prefix: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(f"{prefix}/document.xml", "<document/>")
    return stream.getvalue()


def _pdf() -> bytes:
    from pypdf import PdfWriter

    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(stream)
    return stream.getvalue()


def _image(format_name: str) -> bytes:
    from PIL import Image

    stream = io.BytesIO()
    Image.new("RGB", (2, 2), color=(20, 40, 60)).save(stream, format=format_name)
    return stream.getvalue()


FORMAT_CASES = {
    "pdf": (_pdf, True),
    "doc": (lambda: b"not-an-ole-document", False),
    "docx": (lambda: _ooxml("word"), True),
    "ppt": (lambda: b"not-an-ole-presentation", False),
    "pptx": (lambda: _ooxml("ppt"), True),
    "xls": (lambda: b"not-an-ole-spreadsheet", False),
    "xlsx": (lambda: _ooxml("xl"), True),
    "csv": (lambda: b"name,value\nalpha,1\n", True),
    "txt": (lambda: b"plain UTF-8 text", True),
    "md": (lambda: b"# Heading\n\nBody", True),
    "json": (lambda: b'{"valid": true}', True),
    "png": (lambda: _image("PNG"), True),
    "jpg": (lambda: _image("JPEG"), True),
    "jpeg": (lambda: _image("JPEG"), True),
    "webp": (lambda: _image("WEBP"), True),
}


def test_frontend_picker_and_backend_format_contract_are_exactly_aligned():
    page = (
        Path(__file__).resolve().parents[2]
        / "frontend/lib/pages/personal_knowledge_base_page.dart"
    ).read_text("utf-8")
    block = re.search(
        r"allowedExtensions:\s*const\s*\[(?P<body>.*?)\]",
        page,
        flags=re.DOTALL,
    )
    assert block is not None
    frontend_extensions = set(re.findall(r"'([a-z0-9]+)'", block["body"]))
    backend_extensions = {suffix.removeprefix(".") for suffix in SUPPORTED_MEDIA_TYPES}
    assert frontend_extensions == backend_extensions == set(FORMAT_CASES)


@pytest.mark.parametrize("extension", sorted(FORMAT_CASES))
def test_every_frontend_format_has_success_or_controlled_failure(
    tmp_path, extension: str
):
    factory, succeeds = FORMAT_CASES[extension]
    content = factory()
    storage = PersonalKnowledgeBaseFileStorage(
        tmp_path / extension,
        max_file_bytes=1024 * 1024,
        max_batch_files=2,
        max_batch_bytes=2 * 1024 * 1024,
        max_expanded_bytes=2 * 1024 * 1024,
    )
    upload = _upload(
        f"fixture.{extension}", content, "application/octet-stream"
    )

    if succeeds:
        saved = asyncio.run(storage.save_batch([upload]))
        assert len(saved) == 1
        assert saved[0].media_type == SUPPORTED_MEDIA_TYPES[f".{extension}"]
        assert Path(saved[0].source_path).read_bytes() == content
    else:
        with pytest.raises(InvalidKnowledgeBaseFile):
            asyncio.run(storage.save_batch([upload]))
        assert list(storage.files_root.iterdir()) == []


def test_orphan_cleanup_preserves_retained_and_recent_directories(tmp_path):
    storage = PersonalKnowledgeBaseFileStorage(
        tmp_path / "personal",
        max_file_bytes=1024,
        max_batch_files=2,
        max_batch_bytes=2048,
        max_expanded_bytes=4096,
    )
    retained = str(uuid.uuid4())
    orphan = str(uuid.uuid4())
    recent = str(uuid.uuid4())
    retained_dir = storage.files_root / retained
    orphan_dir = storage.files_root / orphan
    recent_dir = storage.files_root / recent
    retained_dir.mkdir()
    orphan_dir.mkdir()
    recent_dir.mkdir()
    partial = retained_dir / ".uploading"
    partial.write_bytes(b"partial")
    os.utime(orphan_dir, (1, 1))
    os.utime(partial, (1, 1))

    removed = storage.cleanup_orphans(
        retained_file_ids={retained}, retention_seconds=60
    )

    assert retained_dir.is_dir()
    assert not partial.exists()
    assert not orphan_dir.exists()
    assert recent_dir.is_dir()
    assert removed == {
        "file_directories": 1,
        "artifact_directories": 0,
        "partials": 1,
    }


def test_orphan_cleanup_does_not_follow_symlinks(tmp_path):
    storage = PersonalKnowledgeBaseFileStorage(
        tmp_path / "personal",
        max_file_bytes=1024,
        max_batch_files=2,
        max_batch_bytes=2048,
        max_expanded_bytes=4096,
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep"
    marker.write_text("safe", encoding="utf-8")
    link = storage.files_root / str(uuid.uuid4())
    link.symlink_to(outside, target_is_directory=True)

    storage.cleanup_orphans(retained_file_ids=set(), retention_seconds=0)

    assert marker.read_text("utf-8") == "safe"
    assert link.is_symlink()


def test_preview_open_refuses_symlinked_artifact(tmp_path):
    storage = PersonalKnowledgeBaseFileStorage(
        tmp_path / "personal",
        max_file_bytes=1024,
        max_batch_files=2,
        max_batch_bytes=2048,
        max_expanded_bytes=4096,
    )
    file_id = str(uuid.uuid4())
    pipeline = storage.artifacts_root / file_id / "pipeline"
    pipeline.mkdir(parents=True, mode=0o700)
    chunks = pipeline / "chunks.json"
    chunks.write_text("{}", encoding="utf-8")
    os.chmod(chunks, 0o600)
    outside = tmp_path / "outside.txt"
    outside.write_text("do not expose", encoding="utf-8")
    (pipeline / "preview.txt").symlink_to(outside)

    with pytest.raises(PersonalKnowledgeBaseStorageIntegrityError):
        storage.open_text_preview(
            {
                "file_id": file_id,
                "filename": "notes.txt",
                "chunk_manifest_path": str(chunks),
            }
        )


def test_upload_sanitizes_path_and_ignores_spoofed_declared_mime(tmp_path):
    storage = PersonalKnowledgeBaseFileStorage(
        tmp_path / "personal",
        max_file_bytes=1024,
        max_batch_files=2,
        max_batch_bytes=2048,
        max_expanded_bytes=4096,
    )

    saved = asyncio.run(
        storage.save_batch(
            [_upload("../../safe.txt", b"plain text", "application/pdf")]
        )
    )[0]

    assert saved.filename == "safe.txt"
    assert saved.media_type == "text/plain"
    source = Path(saved.source_path).resolve()
    assert source.is_relative_to(storage.files_root)
    if os.name == "posix":
        assert source.stat().st_uid == os.geteuid()
        assert source.stat().st_mode & 0o777 == 0o600
        assert source.parent.stat().st_mode & 0o777 == 0o700


def test_upload_rejects_expanded_office_bomb_and_declared_oversize(tmp_path):
    storage = PersonalKnowledgeBaseFileStorage(
        tmp_path / "personal",
        max_file_bytes=64 * 1024,
        max_batch_files=2,
        max_batch_bytes=64 * 1024,
        max_expanded_bytes=100,
    )
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        output.writestr("[Content_Types].xml", "types")
        output.writestr("word/document.xml", "x" * 10_000)

    with pytest.raises(InvalidKnowledgeBaseFile):
        asyncio.run(
            storage.save_batch(
                [_upload("bomb.docx", archive.getvalue(), "application/octet-stream")]
            )
        )
    with pytest.raises(KnowledgeBaseUploadTooLarge):
        storage.reservation_bytes(
            [
                UploadSource(
                    "large.txt",
                    "text/plain",
                    lambda _size: None,  # type: ignore[arg-type]
                    64 * 1024 + 1,
                )
            ]
        )


def test_multipart_spool_capacity_is_rejected_at_startup(tmp_path, monkeypatch):
    spool = tmp_path / "multipart"
    spool.mkdir(mode=0o700)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        "backend.core.utils.config.shutil.disk_usage",
        lambda _path: usage(100, 100, 0),
    )

    with pytest.raises(RuntimeError, match="safe free space"):
        validate_private_storage_capacity(
            "PERSONAL_KB_TEMP_ROOT", spool, required_bytes=1
        )


def test_durable_personal_data_refuses_job_temporary_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("SLURM_TMPDIR", str(tmp_path))

    with pytest.raises(RuntimeError, match="must not be stored"):
        validate_durable_path("PERSONAL_KB_ROOT", tmp_path / "personal")
