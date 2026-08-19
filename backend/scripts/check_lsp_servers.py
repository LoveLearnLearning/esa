# backend/scripts/check_lsp_servers.py

"""提供 `check_lsp_servers` 数据处理或维护脚本。"""

from __future__ import annotations

import shutil

from backend.core.utils.config import LSP_SERVER_COMMANDS


def main() -> int:
    """运行当前模块的命令行入口。"""
    available: dict[str, str] = {}
    missing: dict[str, str] = {}
    for language, command in LSP_SERVER_COMMANDS.items():
        executable = shutil.which(command[0])
        target = executable or command[0]
        (available if executable else missing)[language] = target

    print("Available LSP servers:")
    for language, executable in sorted(available.items()):
        print(f"  {language:12} {executable}")
    if missing:
        print("Missing LSP servers (the editor will use local fallback):")
        for language, executable in sorted(missing.items()):
            print(f"  {language:12} {executable}")

    return 0 if available else 1


if __name__ == "__main__":
    raise SystemExit(main())
