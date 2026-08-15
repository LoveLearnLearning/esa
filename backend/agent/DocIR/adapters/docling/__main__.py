# backend/agent/DocIR/adapters/docling/__main__.py

"""Command-line entry point for one Docling-to-DocIR conversion."""

from __future__ import annotations

import argparse
from pathlib import Path

from .api import convert_source
from .models import DoclingAdapterConfig


def main(argv: list[str] | None = None) -> int:
    """运行当前模块的命令行入口。

    Args:
        argv: list[str] | None => `argv` 参数。

    Returns:
        int => 处理结果。
    """
    parser = argparse.ArgumentParser(
        description="Convert one local document into a self-contained DocIR bundle"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--max-pages", type=int, default=1000)
    parser.add_argument("--max-file-size", type=int, default=100 * 1024 * 1024)
    args = parser.parse_args(argv)
    document = convert_source(
        args.source,
        args.output,
        DoclingAdapterConfig(
            device=args.device,
            document_timeout_seconds=args.timeout,
            max_num_pages=args.max_pages,
            max_file_size=args.max_file_size,
        ),
        strict=args.strict,
    )
    print(
        f"{document.source.filename}: {len(document.elements)} elements, "
        f"{document.parsed_page_count} pages -> {args.output / 'document.json'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
