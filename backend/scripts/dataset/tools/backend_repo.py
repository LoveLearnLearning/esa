"""定位后端仓库副本，供各 capture 脚本共用。

为什么单独抽出来
----------------
`capture_math_outputs.py` 和 `capture_system_prompts.py` 都要做同一件事：
找到一份后端源码、import 它、把真实输出存下来。两边各写一遍的话，
"默认用本地 clone" 这条规矩早晚会只改一半 —— 这个项目已经因为"只改一半"栽过三次
（见交接文档第零节第 3 条）。

默认顺序
--------
1. `--repo` 指定的路径
2. 环境变量 `ESA_BACKEND_REPO`
3. `~/esa`（约定位置，用 `git -C ~/esa pull` 更新）
4. 都没有 → 下载 tarball 快照到临时目录

⚠️ tarball 是最后的退路，不是默认：它抓的是 GitHub 上那一刻的 main，
抓不到本地刚 pull 的改动，而且**不会报任何错**。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

TARBALL = "https://codeload.github.com/LoveLearnLearning/esa/tar.gz/refs/heads/main"
DEFAULT_LOCAL = Path("~/esa").expanduser()


class BackendRepo:
    """一份后端源码副本。用 `with` 管理，临时下载的副本退出时自动删。"""

    def __init__(self, path: Path, kind: str, tmpdir: Path | None = None):
        self.path = path
        # 来源**类型**（local-clone / tarball:main），不是路径 —— 见 describe()
        self.kind = kind
        self._tmpdir = tmpdir

    def __enter__(self) -> "BackendRepo":
        return self

    def __exit__(self, *exc) -> None:
        if self._tmpdir is not None:
            shutil.rmtree(self._tmpdir, ignore_errors=True)

    def describe(self) -> str:
        """写进缓存 _meta 的来源说明：来源类型 + commit。

        ⚠️ **绝不能带本机绝对路径**。这些缓存要跟着数据集发到公开仓库，
        而 home 目录下的绝对路径会暴露开发者的系统用户名 ——
        `make_publish_dir.py` 的泄漏扫描把它列为必拦项。
        commit 才是真正有溯源价值的信息，本地路径对读者没有任何意义。
        （这段注释本身第一版就写了个字面路径例子，被那个扫描拦下来了。检查是有效的。）
        """
        commit = self.head_commit()
        return f"{self.kind}@{commit}" if commit else self.kind

    def head_commit(self) -> str | None:
        try:
            out = subprocess.run(
                ["git", "-C", str(self.path), "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() or None if out.returncode == 0 else None


def _extract(dest: Path) -> Path:
    print(f"本地找不到后端副本，下载快照 → {dest}")
    print("⚠️ 快照抓的是 GitHub 上此刻的 main，抓不到你本地的改动。"
          "建议 clone 到 ~/esa 后用 git pull。")
    tgz = dest / "esa.tar.gz"
    urllib.request.urlretrieve(TARBALL, tgz)
    with tarfile.open(tgz) as tf:
        try:
            tf.extractall(dest, filter="data")
        except TypeError:
            # filter= 是 PEP 706 加的，老一点的 3.9/3.10/3.11 补丁版没有。
            # 解到临时目录、解完就删，退回旧行为可以接受。
            tf.extractall(dest)  # noqa: S202
    roots = [p for p in dest.iterdir() if p.is_dir() and (p / "backend").exists()]
    if not roots:
        raise SystemExit("解包后找不到 backend/ 目录，仓库结构可能变了")
    return roots[0]


def resolve(repo_arg: str | None = None, *, download: bool = False) -> BackendRepo:
    """按上面的顺序定位后端仓库。找不到 backend/ 一律吵，不要静默继续。"""
    if download and repo_arg:
        raise SystemExit("--repo 和 --download 不能同时给：说不清到底该用哪一份")

    if not download:
        candidates: list[tuple[Path, str]] = []
        if repo_arg:
            candidates.append((Path(repo_arg).expanduser().resolve(), "--repo"))
        elif env := os.environ.get("ESA_BACKEND_REPO"):
            candidates.append((Path(env).expanduser().resolve(), "$ESA_BACKEND_REPO"))
        else:
            candidates.append((DEFAULT_LOCAL, "~/esa"))

        path, how = candidates[0]
        if (path / "backend").exists():
            print(f"用本地后端副本（{how}）：{path}")
            return BackendRepo(path, kind="local-clone")
        if repo_arg or os.environ.get("ESA_BACKEND_REPO"):
            # 显式指定却不存在，是配置错了，不该悄悄换成下载。
            raise SystemExit(f"{path} 下没有 backend/ 目录（来源：{how}）")

    tmp = Path(tempfile.mkdtemp(prefix="esa_backend_"))
    return BackendRepo(_extract(tmp), kind="tarball:main", tmpdir=tmp)
