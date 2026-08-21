"""Tests for bounded Office preview conversion."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.agent.rag.personal.preview import LibreOfficePreviewConverter


def _converter_script(path: Path, *, valid_pdf: bool = True) -> Path:
    payload = "%PDF-1.4\\n1 0 obj\\n<<>>\\nendobj\\n%%EOF\\n" if valid_pdf else "not pdf"
    path.write_text(
        "#!/bin/sh\n"
        "output=''\n"
        "source=''\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = '--outdir' ]; then shift; output=$1; "
        "else source=$1; fi\n"
        "  shift\n"
        "done\n"
        "name=${source##*/}\n"
        "stem=${name%.*}\n"
        f"printf '%b' '{payload}' > \"$output/$stem.pdf\"\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o700)
    return path


def test_converter_uses_isolated_output_and_commits_private_pdf(tmp_path):
    binary = _converter_script(tmp_path / "fake-libreoffice")
    source = tmp_path / "lecture;not-a-command.docx"
    source.write_bytes(b"office source")
    converter = LibreOfficePreviewConverter(binary, max_output_bytes=1024)

    converted = converter.convert(source, tmp_path / "work")
    destination = tmp_path / "artifacts" / "preview.pdf"
    destination.parent.mkdir(mode=0o700)
    converter.commit(converted, destination)

    assert destination.read_bytes().startswith(b"%PDF-")
    assert destination.stat().st_mode & 0o077 == 0
    assert not (tmp_path / "not-a-command").exists()
    assert len(converter.configuration_fingerprint) == 64


def test_converter_rejects_non_pdf_output(tmp_path):
    binary = _converter_script(tmp_path / "bad-libreoffice", valid_pdf=False)
    source = tmp_path / "lecture.docx"
    source.write_bytes(b"office source")
    converter = LibreOfficePreviewConverter(binary, max_output_bytes=1024)

    with pytest.raises(RuntimeError, match="not PDF"):
        converter.convert(source, tmp_path / "work")


def test_converter_rejects_output_over_limit(tmp_path):
    binary = _converter_script(tmp_path / "large-libreoffice")
    source = tmp_path / "lecture.docx"
    source.write_bytes(b"office source")
    converter = LibreOfficePreviewConverter(binary, max_output_bytes=4)

    with pytest.raises(RuntimeError, match="output limit"):
        converter.convert(source, tmp_path / "work")
