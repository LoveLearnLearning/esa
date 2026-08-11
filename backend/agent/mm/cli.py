"""mm 独立摄取/查询命令行。"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
from pathlib import Path

from .service import MultimodalIngestionService


async def _run(args: argparse.Namespace) -> int:
    service = MultimodalIngestionService()
    if args.command == "ingest":
        prepared = await service.prepare_files(tuple(args.files))
        print(
            json.dumps(
                [
                    {
                        "source": str(item.source_path),
                        "mode": item.mode.value,
                        "token_count": item.token_count,
                        "document_id": item.document.document_id,
                        "manifest": str(item.manifest_path),
                    }
                    for item in prepared
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    prepared = await service.prepare_file(args.file)
    result = prepared.context_for(args.query)
    if isinstance(result, str):
        print(result)
    else:
        print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ESA 多模态附件摄取")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("files", nargs="+", type=Path)
    query = subparsers.add_parser("query")
    query.add_argument("file", type=Path)
    query.add_argument("--query", required=True)
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())

