"""只挑出**需要上传的那些文件**，避开 GitHub 网页单次 100 个的上限。

    # 与 fork 现在的状态比（**日常就用这个** —— 上传的落点就是 fork）
    python3 dataset/tools/make_upload_delta.py \
        --publish ~/Desktop/esa-dataset-pr/dataset \
        --against-ref fork/main --repo ~/esa \
        --out ~/Desktop/esa-upload-delta

    # 与某个已检出的目录比
    python3 dataset/tools/make_upload_delta.py --publish … --against /tmp/up/... --out …

为什么比较对象必须是 **fork** 而不是上游
----------------------------------------
改动的流向是：本机仓库 → 上传到 fork → PR → 上游（很慢，以天计）。
所以**上传的落点是 fork**，要问的是「相对 fork 现在的样子，我要传哪些」。

拿上游当比较对象，会把**上一批已经传进 fork 的文件重新算成待传** ——
于是每次都在重传同样的东西，且掩盖了真正的增量。2026-08-26 第一次上传之后
就出现了这个情况（上游尚未合并我们的 PR，比上游得到 15 个，比 fork 只剩几个）。

⚠️ 但 **sync fork 会把 fork 重置回上游**。sync 之后再比，差集自然又变大 ——
那是对的，不是 bug：那时 fork 里确实没有我们的东西了。

🔴 网页上传**不会删文件**
--------------------------
拖上去只会新增和覆盖。所以「对方有、我们没有」的文件会**留在那儿**，
且不会有任何提示。本工具单独列出这一类，要删得**人去网页上手动删**。

准备工作（只做一次）
--------------------
    cd ~/esa && git remote add fork https://github.com/chenweihang0160-alt/esa
    git fetch fork
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SUBTREE = "backend/scripts/dataset"


def rel_files(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file()}


def as_dataset_dir(p: Path, what: str) -> Path:
    """把路径归一到**那个 `dataset` 目录本身**，两边才比得起来。

    🔴 2026-08-26 查出来的两个坑，都是「两边不同根」：

    1. `checkout_ref` 返回的是 `.../backend/scripts/dataset`（dataset 目录本身），
       而 `make_publish_dir` 的产出是**含** `dataset/` 的上一层。
       原来直接拿两个根去比，路径一边是 `tools/x.py`、一边是 `dataset/tools/x.py`，
       **永远匹配不上，全部报成新增** —— `--against-ref` 一直是坏的。
    2. 发布目录根上还躺着 `.DS_Store` 和一整个 `.obsidian/`
       （那个文件夹被 Obsidian 打开过；`make_publish_dir` 按设计不删非自己产出的东西）。
       归一到 dataset 目录之后，它们自然被排除在外 —— 上传目标本来就只有
       `backend/scripts/dataset/`。
    """
    if (p / "esa").is_dir():
        return p
    if (p / "dataset" / "esa").is_dir():
        return p / "dataset"
    sys.exit(f"❌ {what} 里找不到 dataset 目录（既不是它本身，下面也没有）：{p}")


def checkout_ref(repo: str, ref: str, dest: Path) -> Path:
    """把某个 git ref 下的 `backend/scripts/dataset` 检出到临时目录。

    用 `git archive | tar` 而不是 `git checkout`：**不碰工作区**，
    所以你手上有没有未提交的改动、在哪个分支，都不受影响。
    """
    dest.mkdir(parents=True, exist_ok=True)
    ar = subprocess.run(["git", "archive", ref, SUBTREE],
                        cwd=repo, capture_output=True)
    if ar.returncode != 0:
        sys.exit(
            f"❌ git archive {ref} 失败：{ar.stderr.decode(errors='replace').strip()}\n"
            f"   ⚠️ `--against-ref` 是给 **fork 的 ref** 用的（那边的布局才是 {SUBTREE}）。\n"
            f"      本机仓库的布局是 `dataset/`，拿本机的 commit 当 ref 必然报这个错 ——\n"
            f"      要和本机某次提交比，用：\n"
            f"        git archive <ref> dataset | tar -x -C <临时目录>\n"
            f"        python3 tools/make_upload_delta.py --publish ... --against <临时目录>\n"
            f"   fork 还没加过远端的话：cd {repo} && "
            "git remote add fork https://github.com/chenweihang0160-alt/esa && git fetch fork\n"
            "   ⚠️ 加完远端记得 `git remote remove fork` —— 它带 push URL，"
            "而这个仓库的 git 历史里有真名邮箱，绝不能推。")
    tar = subprocess.run(["tar", "-x", "-C", str(dest)], input=ar.stdout, capture_output=True)
    if tar.returncode != 0:
        sys.exit(f"❌ 解包失败：{tar.stderr.decode(errors='replace').strip()}")
    out = dest / SUBTREE
    if not out.is_dir():
        sys.exit(f"❌ {ref} 里没有 {SUBTREE}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="挑出需要上传的差集")
    ap.add_argument("--publish", required=True, help="make_publish_dir.py 的产出目录")
    ap.add_argument("--against", help="比较对象：已检出的 dataset 目录")
    ap.add_argument("--against-ref", help="比较对象：git ref（如 fork/main），需配 --repo")
    ap.add_argument("--repo", help="git 仓库路径，配合 --against-ref")
    ap.add_argument("--out", required=True, help="差集落到哪")
    args = ap.parse_args()

    if bool(args.against) == bool(args.against_ref):
        ap.error("--against 与 --against-ref 二选一")
    if args.against_ref and not args.repo:
        ap.error("--against-ref 需要 --repo")

    pub, out = Path(args.publish), Path(args.out)
    if not pub.is_dir():
        sys.exit(f"❌ --publish 不是目录：{pub}")

    tmp = None
    if args.against_ref:
        tmp = tempfile.TemporaryDirectory()
        up = checkout_ref(args.repo, args.against_ref, Path(tmp.name))
        label = args.against_ref
    else:
        up = Path(args.against)
        label = str(up)
        if not up.is_dir():
            sys.exit(f"❌ --against 不是目录：{up}")

    pub_ds = as_dataset_dir(pub, "--publish")
    up_ds = as_dataset_dir(up, "比较对象")
    mine, theirs = rel_files(pub_ds), rel_files(up_ds)
    added = sorted(mine - theirs)
    only_up = sorted(theirs - mine)
    changed = sorted(f for f in (mine & theirs)
                     if not filecmp.cmp(pub_ds / f, up_ds / f, shallow=False))

    if out.exists():
        shutil.rmtree(out)
    # 差集里保留 `dataset/` 这一层：网页上拖的就是这个文件夹
    for f in added + changed:
        dst = out / "dataset" / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pub_ds / f, dst)

    print(f"比较对象：{label}")
    if args.against_ref:
        print("⚠️ 比较对象是 **git 树**，不是 fork 本身。")
        print("   `.gitignore` 里的东西不在 git 树里、却会被发布"
              "（如 `dataset/data/states_*.csv`），会被**误报成新增**。")
        print("   拖之前对着 fork 网页确认一下这些文件在不在，别白传。")
    print(f"新增 {len(added)}　改动 {len(changed)}　→ 要上传 {len(added) + len(changed)} 个")
    for f in added:
        print(f"  ＋ {f}")
    for f in changed:
        print(f"  ✎ {f}")

    if only_up:
        print(f"\n🔴 对方有、我们没有的 {len(only_up)} 个 —— "
              "网页上传**不会删它们**，要删得人去网页手动删：")
        for f in only_up:
            print(f"     {f}")
    else:
        print("\n✅ 没有「对方有、我们没有」的文件——不会留下孤儿")

    n = len(added) + len(changed)
    print(f"\n→ {out}（{n} 个文件，网页单次上限 100）")
    if n == 0:
        print("   （无需上传：发布目录与比较对象逐字节一致）")
    elif n > 100:
        print("⚠️ 超过 100，得分两次拖：按顶层子目录分")
    print("⚠️ 拖之前先 sync fork 的话，差集会变大——sync 会把 fork 重置回上游。")
    if tmp:
        tmp.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
