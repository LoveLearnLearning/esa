# backend/agent/DocIR/paths.py

"""

这个文件干什么：DocIR 在 ESA 工作区中的可移植路径解析。

直白点说就是：无论程序从哪个目录启动，都帮它可靠地找到 ESA 项目根目录。

DocIR 在 ESA 工作区中的可移植路径解析。
"""

from __future__ import annotations

import os
from pathlib import Path


def workspace_root() -> Path:
    """优先使用显式配置，否则从 ``backend/agent/DocIR`` 反推仓库根目录。"""

    configured = os.environ.get("ESA_WORKSPACE") or os.environ.get("RAG_WORKSPACE")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


WORKSPACE_ROOT = workspace_root()
