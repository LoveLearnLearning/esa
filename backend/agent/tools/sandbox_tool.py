"""Agent-facing contract for the restricted command sandbox."""

from __future__ import annotations

from typing import Any

from backend.agent.tools.tools import tr


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "run_in_sandbox",
            "description": (
                "在当前用户和对话专属的隔离沙箱中执行命令。"
                "沙箱默认无网络，只能读系统运行库并读写 /workspace；"
                "适合运行代码、测试和受控的数据处理。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的 shell 命令；工作文件放在 /workspace",
                    },
                    "workdir": {
                        "type": "string",
                        "description": "/workspace 内的相对目录，默认为根目录",
                        "default": ".",
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "description": "本次命令超时时间，由服务端限制最大值",
                        "default": 30,
                    },
                },
                "required": ["command"],
            },
        },
    }
)
def run_in_sandbox(
    command: str,
    workdir: str = ".",
    timeout_seconds: float = 30,
) -> dict[str, Any]:
    """Reject unbound calls; production execution is context-bound."""

    del command, workdir, timeout_seconds
    raise RuntimeError("run_in_sandbox requires the application sandbox runtime")
