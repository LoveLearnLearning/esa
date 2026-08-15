# backend/agent/DocIR/adapters/paddleocr/__main__.py

"""Command-line entry point for the PaddleOCR Adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .api import convert_source
from .models import PaddleOCRAdapterConfig


def main() -> None:
    """运行当前模块的命令行入口。"""
    parser = argparse.ArgumentParser(description="Convert a local PDF/image to DocIR")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--device", default="gpu:0")
    parser.add_argument(
        "--model-cache", type=Path, default=Path("/tmp/esa-paddleocr-cache")
    )
    parser.add_argument("--max-pages", type=int, default=1000)
    parser.add_argument("--max-file-size", type=int, default=100 * 1024 * 1024)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    config = PaddleOCRAdapterConfig(
        device=args.device,
        model_cache_dir=args.model_cache,
        max_num_pages=args.max_pages,
        max_file_size=args.max_file_size,
    )
    document = convert_source(args.source, args.output, config, strict=args.strict)
    print(
        json.dumps(
            {
                "document_id": document.document_id,
                "pages": document.parsed_page_count,
                "elements": len(document.elements),
                "assets": len(document.assets),
                "validation": document.validation.status.value,
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
