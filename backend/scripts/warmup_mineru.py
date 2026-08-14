"""Warm the resident MinerU pipeline through its HTTP API."""

from __future__ import annotations

import argparse
import io
import zipfile

import httpx


def _minimal_pdf() -> bytes:
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length 43 >>\nstream\nBT /F1 12 Tf 72 720 Td (ESA MinerU warmup) Tj ET\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    )
    document = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{number} 0 obj\n".encode())
        document.extend(body)
        document.extend(b"\nendobj\n")
    xref_offset = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode())
    document.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(document)


def warmup(api_url: str, timeout_seconds: float) -> None:
    form = {
        "lang_list": "ch",
        "backend": "pipeline",
        "parse_method": "auto",
        "return_md": "true",
        "return_middle_json": "true",
        "return_model_output": "true",
        "return_content_list": "true",
        "return_images": "false",
        "response_format_zip": "true",
    }
    timeout = httpx.Timeout(timeout_seconds, connect=10.0)
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        response = client.post(
            f"{api_url.rstrip('/')}/file_parse",
            data=form,
            files={"files": ("warmup.pdf", _minimal_pdf(), "application/pdf")},
        )
        response.raise_for_status()
    if not zipfile.is_zipfile(io.BytesIO(response.content)):
        raise RuntimeError("MinerU warmup did not return a ZIP bundle")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=7200.0)
    args = parser.parse_args()
    warmup(args.api_url, args.timeout_seconds)


if __name__ == "__main__":
    main()
