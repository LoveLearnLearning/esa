"""路径定位：让这套流水线放在仓库里的**任何位置**都能跑，也不挑当前工作目录。

为什么需要这个模块
------------------
组长要求把 `dataset/` 放进后端仓库的 `backend/scripts/` 下再发 PR。
实测搬过去之后有两类东西会坏（其余全好 —— 那些 `parents[2]` 算出来的路径
是跟着目录一起搬的，反而一处都不用改）：

1. **CWD 相对的默认值**，比如 `--schemas` 默认写成 `dataset/schemas/tool_schemas.json`。
   它同时假定了两件事：你从仓库根启动、且 `dataset/` 就在仓库根下。
   搬进 `backend/scripts/` 之后两条都不成立。

2. **`fixtures.KG_DIRS`** 按 `<上两级>/backend/agent/memories/data/knowledge_graph`
   找知识图谱。搬进 `backend/scripts/dataset/` 之后，"上两级"是 `backend/scripts`，
   于是它去找 `backend/scripts/backend/agent/...` —— 不存在。
   这是整套流水线里**唯一**一处真正跨出 `dataset/` 边界的依赖。

所以这里定义两个概念，别再混用：

    DATASET_DIR   `dataset/` 这个文件夹自己。种子、数据、缓存、schema 全在它下面，
                  跟着它一起搬，永远不会错。
    repo_root()   外层仓库的根。**只用于找后端自己的东西**（目前只有知识图谱一处）。

判据是往上找 `backend/` 或 `.git`，而不是写死"上两级" —— 写死层数正是这次要修的病。
"""

from __future__ import annotations

from pathlib import Path

# `dataset/` 目录本身。本文件在 `dataset/esa/paths.py`，所以往上两级。
# 这个 parents[1] 和被修掉的那些 parents[2] 不是一回事：
# 它算的是"我自己所在的那个包的上级"，包整体搬走时结果跟着变，永远指向正确的 dataset/。
DATASET_DIR = Path(__file__).resolve().parents[1]

# 认定"这是仓库根"的标志。backend/ 排在前面：数据集既可能待在后端仓库里
# （`backend/scripts/dataset/`），也可能待在独立仓库里（根下直接是 dataset/）。
_ROOT_MARKERS = ("backend", ".git")


def repo_root(start: Path | None = None) -> Path:
    """往上找外层仓库根。找不到就退回 `DATASET_DIR` 的上一级。

    退回而不是抛错，是因为**找不到不一定是错的**：
    独立发布仓库里就没有 `backend/`，知识图谱直接躺在根上，
    `fixtures.kg_files()` 的第二个候选目录正好覆盖那种情况。
    真正找不到知识图谱时由那边抛错，错误信息也更具体。
    """
    here = (start or DATASET_DIR).resolve()
    for d in (here, *here.parents):
        if any((d / m).exists() for m in _ROOT_MARKERS):
            return d
    return DATASET_DIR.parent


def in_dataset(*parts: str) -> Path:
    """`dataset/` 下的路径。给 argparse 默认值用，替掉 CWD 相对的字符串。"""
    return DATASET_DIR.joinpath(*parts)
