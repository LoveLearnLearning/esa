# backend/agent/rag/paths.py

"""

这个文件干什么：RAG 包的可移植工作区路径解析。

直白点说就是：无论程序从哪个目录启动，都帮 RAG 模块找到 ESA 项目根目录。
"""

from __future__ import annotations

import os
from pathlib import Path


def workspace_root() -> Path:
    """优先使用显式配置，否则从 ``backend/agent/rag`` 反推仓库根目录。"""

    configured = os.environ.get("ESA_WORKSPACE") or os.environ.get("RAG_WORKSPACE")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


# 向后兼容仍按常量导入路径的 CLI、评估脚本和测试。
WORKSPACE_ROOT = workspace_root()
