# backend/agent/tools/export_schemas.py

"""导出当前 ToolRegistry 的 JSON Schema 快照。

运行：
    python -m backend.agent.tools.export_schemas

默认覆盖 backend/agent/tools/tool_schemas.json，使版本化快照与实际注册工具保持一致。
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.agent.tools import tr

OUTPUT_PATH = Path(__file__).resolve().with_name("tool_schemas.json")


def export_tool_schemas(output_path: str | Path = OUTPUT_PATH) -> Path:
    """导出 `tool schemas` 相关数据。"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(tr.schemas, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def main() -> None:
    """运行当前模块的命令行入口。"""
    path = export_tool_schemas()
    print(f"exported {len(tr.schemas)} tool schemas -> {path}")


if __name__ == "__main__":
    main()
