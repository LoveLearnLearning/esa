# backend/agent/mm/tests/test_parser_api.py

"""验证 `parser_api` 相关行为与回归场景。"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from backend.agent.mm.parser import MinerUDocumentParser, _safe_extract_zip


def _mineru_zip() -> bytes:
    """处理 `_mineru_zip` 相关逻辑。"""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        bundle.writestr("source/auto/source_middle.json", "{}")
        bundle.writestr("source/auto/source_content_list_v2.json", "[]")
    return stream.getvalue()


def test_parse_with_api_materializes_zip_bundle(tmp_path: Path, monkeypatch) -> None:
    """验证 `parse_with_api_materializes_zip_bundle` 场景。"""
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    raw_root = tmp_path / "mineru"
    raw_root.mkdir()
    (raw_root / "stale.txt").write_text("stale", encoding="utf-8")
    captured: dict[str, object] = {}

    class Response:
        """表示 `response` 数据结构。"""
        def __enter__(self):
            """进入上下文并返回可用资源。"""
            return self

        def __exit__(self, *_args):
            """退出上下文并释放相关资源。"""
            return None

        def raise_for_status(self) -> None:
            """处理 `raise_for_status` 相关逻辑。"""
            return None

        def iter_bytes(self):
            """处理 `iter_bytes` 相关逻辑。"""
            yield _mineru_zip()

    class Client:
        """封装 `Client` 的状态与行为。"""
        def __init__(self, **_kwargs):
            """初始化 `Client` 实例。"""
            pass

        def __enter__(self):
            """进入上下文并返回可用资源。"""
            return self

        def __exit__(self, *_args):
            """退出上下文并释放相关资源。"""
            return None

        def stream(self, method, url, *, data, files):
            """流式处理 `stream` 相关数据。

            Args:
                method: object => `method` 参数。
                url: object => `url` 参数。
                data: object => 输入数据。
                files: object => `files` 参数。

            Returns:
                object => 处理结果。
            """
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
    """验证 `safe_extract_zip_rejects_parent_traversal` 场景。"""
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.txt", "unsafe")

    with pytest.raises(ValueError, match="unsafe path"):
        _safe_extract_zip(archive, tmp_path / "output")

    assert not (tmp_path / "outside.txt").exists()
