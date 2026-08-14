from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from backend.agent.mm.parser import MinerUDocumentParser, _safe_extract_zip


def _mineru_zip() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        bundle.writestr("source/auto/source_middle.json", "{}")
        bundle.writestr("source/auto/source_content_list_v2.json", "[]")
    return stream.getvalue()


def test_parse_with_api_materializes_zip_bundle(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    raw_root = tmp_path / "mineru"
    raw_root.mkdir()
    (raw_root / "stale.txt").write_text("stale", encoding="utf-8")
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self):
            yield _mineru_zip()

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def stream(self, method, url, *, data, files):
            captured.update(method=method, url=url, data=data, files=files)
            return Response()

    monkeypatch.setattr("backend.agent.mm.parser.httpx.Client", Client)
    parser = MinerUDocumentParser(
        command=tmp_path / "unused",
        api_url="http://127.0.0.1:51026",
    )

    parser._parse_with_api(source, raw_root)

    assert captured["method"] == "POST"
    assert captured["url"] == "http://127.0.0.1:51026/file_parse"
    assert captured["data"]["response_format_zip"] == "true"
    assert (raw_root / "source/auto/source_middle.json").is_file()
    assert not (raw_root / "stale.txt").exists()


def test_safe_extract_zip_rejects_parent_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.txt", "unsafe")

    with pytest.raises(ValueError, match="unsafe path"):
        _safe_extract_zip(archive, tmp_path / "output")

    assert not (tmp_path / "outside.txt").exists()
