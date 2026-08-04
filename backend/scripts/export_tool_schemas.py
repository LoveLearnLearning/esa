# backend/scripts/export_tool_schemas.py


import argparse
import json
from pathlib import Path

from backend.agent.tools import tr


def export_tool_schemas(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            tr.schemas,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="导出所有 Tool Schema")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tool_schemas.json"),
        help="输出 JSON 文件路径",
    )
    args = parser.parse_args()
    export_tool_schemas(args.output)
    print(f"已导出 {len(tr.schemas)} 个工具到 {args.output}")


if __name__ == "__main__":
    main()
