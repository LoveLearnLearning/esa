"""检查后端有没有新提交，**并跑出它对我们有没有影响**。

    python3 dataset/tools/check_backend_updates.py           # 人看的完整报告
    python3 dataset/tools/check_backend_updates.py --quiet   # 只在需要动手时才出声（给定时任务用）

为什么不是"看一眼有没有新 commit"
----------------------------------
这个项目最贵的一类错误是「需要知道线上长什么样时，没去跑，而是凭看起来合理写了一版」，
已重演六次。commit message 尤其不可信 —— 8/12 那次 24 条提交里
**整条 rag_dev 分支并入、8000+ 行**，结论却是零影响；而另一次只有 18 条，
却让 18 种提示词哈希完全不重叠、必须全量重生成。

所以本工具的核心不是列 commit，是**跑七个 capture 再比缓存**（剔 _meta、屏蔽易变字段）。
列 commit 只是给人看的上下文，判定一律以缓存 diff 为准。

⚠️ 但缓存 diff **不是唯一判据**（2026-08-17 补的教训，见交接文档 5.24）：
它跑的是**我们自己的 capture 脚本**。脚本要是抓错了层，它在新旧后端上会抓出
同样的（错的）东西，于是永远报「零影响」—— `ContextComposer` 8/14 就上线了，
我们的提示词少了三段，而这个工具连报三天绿。
所以另加一道**不经过我们 capture** 的检查：上游有没有动
`backend/scripts/dataset/` 底下的文件（那是我们自己的代码）。
命中就必须人来三方合并，缓存全绿也不放行。

不会动到什么
------------
- **不改你的 `~/esa` 工作区**：用 `git worktree` 在临时目录检出 `origin/main`，
  capture 通过 `--repo` 指过去，跑完就删。你手上没 pull 也能查。
- **不覆盖 `data/cache/`**：capture 写到临时目录，只读地比对。
  真要更新缓存，是另一个动作（按报告末尾的命令手动跑）。

退出码
------
  0  没有新提交，或有新提交但**零影响**
  1  要动手：缓存变了（重跑生成器），**或**上游动了我们自己的文件（要三方合并）
  2  出错（找不到仓库、fetch 失败等）
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "dataset/data/cache"

# 缓存名 → (capture 脚本, 缓存文件相对 ROOT 的路径, 这份缓存变了要重跑哪些生成器)
#
# ⚠️ 2026-08-16 从四份补到七份。原来后三份没进来，理由是「要 venv」——
# 而 2026-08-15 已实测本机 python3 跑得通，**理由失效了，缺口还留着**：
# 后端动了记忆/学情工具或工具注册，这个检查会照样报「零影响」。
# 那正是本项目栽过十二次的「数据错、仪表盘绿」。
CAPTURES = {
    "math_real": (
        "capture_math_outputs.py",
        "dataset/data/cache/math_real.json",
        ["gen_calculators.py", "gen_tool_errors.py"],
    ),
    "skills_bodies": (
        "capture_skill_bodies.py",
        "dataset/data/cache/skills_bodies.json",
        ["全部生成器（Skill 正文进 system prompt）"],
    ),
    "system_prompts": (
        "capture_system_prompts.py",
        "dataset/data/cache/system_prompts.json",
        ["全部生成器"],
    ),
    "parser_golden": (
        "capture_parser_golden.py",
        "dataset/data/cache/parser_golden.json",
        ["不用重跑生成器，但 test_parser_compat.py 会红 → 改 esa/backend_parser.py"],
    ),
    "memory_real": (
        "capture_memory_tools.py",
        "dataset/data/cache/memory_real.json",
        ["test_fixture_contract.py 会红 → 改 esa/fixtures.py 记忆侧 → gen_new_tools.py"],
    ),
    "learning_real": (
        "capture_learning_tools.py",
        "dataset/data/cache/learning_real.json",
        ["test_fixture_contract.py 会红 → 改 esa/fixtures.py 学情侧 → gen_new_tools.py"],
    ),
    "tool_schemas": (
        "capture_tool_schemas.py",
        "dataset/schemas/tool_schemas.json",
        ["schema_version 会变 → **全量重跑生成器**"],
    ),
}

# 每次跑都会变、且**不携带结构信息**的叶子字段。
#
# 记忆/学情两个 capture 在临时 SQLite 上真跑，所以每次都是新的主键和写入时刻；
# `recommended_date` 是「今天 + N 天」。同一秒内跑两次就能差 100 多处
# （2026-08-16 实测：memory 102 处、learning 103 处），全落在这几个名字上。
# 不屏蔽的话这个检查每天都红，而**只会误报的检查和不报警的检查一样糟**。
#
# ⚠️ 屏蔽是**换值**不是删键 —— 删了键就看不出后端哪天把某个字段去掉了，
# 而字段消失恰恰是我们最需要被告知的那种变化。
VOLATILE_FIELDS = {
    "memory_id", "candidate_id", "id",
    "created_at", "updated_at", "confirmed_at", "expires_at",
    "last_practiced_at", "recommended_date",
}

# 我们自己的代码在后端仓库里的落点（组长指定 `backend/scripts/`）。
# 上游动了这底下的东西 = 别人在改我们的文件，必须三方合并而不是覆盖。
OUR_FILES_PREFIX = "backend/scripts/dataset/"

# 只是给人看的提示，**不作为判定依据**。判定一律看缓存 diff。
TRIGGER_HINTS = [
    ("tool_schemas.json", "工具 schema"),
    ("math_tools/", "计算器"),
    ("skills/", "Skill 正文"),
    ("system.py", "system prompt"),
    ("build_prompt", "system prompt"),
    ("workspaces.py", "Workspace"),
    ("parser.py", "输出解析"),
    ("tool_arguments.py", "参数归一化"),
]


def run(cmd: list[str], cwd: Path | None = None) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}\n{r.stderr.strip()}")
    return r.stdout.strip()


def baseline_commit() -> str:
    """从各份缓存的 `_meta.source_repo` 读基线。彼此不一致本身就是问题。

    ⚠️ `schemas/tool_schemas.json` 顶层是个 list，没有 `_meta`
    （它的元信息在旁边的 `tool_schemas_meta.json`），所以**跳过它**，
    不能因此把整个检查搞崩。
    """
    seen: dict[str, list[str]] = {}
    for name, (_script, relpath, _actions) in CAPTURES.items():
        p = ROOT / relpath
        if not p.exists():
            raise RuntimeError(f"缓存不存在：{p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "_meta" not in data:
            continue
        src = data["_meta"].get("source_repo", "")
        sha = src.split("@")[-1] if "@" in src else "?"
        seen.setdefault(sha, []).append(name)

    if len(seen) > 1:
        detail = "；".join(f"{sha}: {', '.join(names)}" for sha, names in seen.items())
        raise RuntimeError(
            f"各份缓存的基线不一致（{detail}）。\n"
            "说明上次抓取只抓了一部分 —— 先把 capture 全跑一遍对齐，再来查更新。"
        )
    return next(iter(seen))


def _mask_volatile(o):
    """把 `VOLATILE_FIELDS` 里的叶子值换成占位符，键本身保留。

    只对**标量**下手：万一后端把某个 id 改成对象，那是结构变化，必须报出来。
    """
    if isinstance(o, dict):
        return {
            k: ("<volatile>"
                if k in VOLATILE_FIELDS and not isinstance(v, (dict, list))
                else _mask_volatile(v))
            for k, v in o.items()
        }
    if isinstance(o, list):
        return [_mask_volatile(x) for x in o]
    return o


def diff_cache(old: Path, new: Path) -> bool:
    """内容是否相同。两处归一，都不是可有可无的：

    1. **剔除 `_meta`** —— 它存着来源 commit，必然变。
       只看 `git diff --stat` 会看到每个文件都"改了"，那是假信号。
    2. **屏蔽 `VOLATILE_FIELDS`** —— 见该常量的注释。
    """
    a = json.loads(old.read_text(encoding="utf-8"))
    b = json.loads(new.read_text(encoding="utf-8"))
    if isinstance(a, dict):
        a.pop("_meta", None)
    if isinstance(b, dict):
        b.pop("_meta", None)
    return _mask_volatile(a) == _mask_volatile(b)


def check_error_registry(repo: Path) -> list[str]:
    """核对 `seeds/tool_errors.yaml` 登记的报错文案**在后端源码里还在不在**。

    ⚠️ 这是 2026-08-15 补的，补的是一个真实盲区：

    `validate.py` 的 `check_error_texts_registered` 只保证「样本里用的文案
    在登记表里有」，**不保证登记表里的文案后端还存在**。方向是单向的。

    后果当天就出现了：后端 `1b64473` 把 web_search 从本地 SearXNG 整个换成
    You.com MCP，5 句 SearXNG 报错文案（"搜索请求超时"、"SearXNG 返回 HTTP 502" …）
    在后端一句不剩，而我们有 5 条样本逐字引用它们 ——
    **validate 全绿，数据却在教模型识别一组线上永不出现的文案。**

    这里做的就是把箭头反过来：拿登记表去后端源码里搜一遍，搜不到就喊。
    """
    import yaml  # noqa: PLC0415

    seeds = ROOT / "dataset/seeds/tool_errors.yaml"
    if not seeds.exists():
        return []
    registry = yaml.safe_load(seeds.read_text(encoding="utf-8")).get("registry", {})
    literals = [item["text"] for item in registry.get("literal", [])]

    # 后端源码全文，一次读完再比，比逐条 grep 快得多
    corpus = []
    for path in (repo / "backend").rglob("*.py"):
        if "/tests/" in str(path) or "__pycache__" in str(path):
            continue
        try:
            corpus.append(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):
            continue
    blob = "\n".join(corpus)

    missing = []
    for text in literals:
        # 样本里存的可能带 "[Error]: " 前缀，那是 tool_register 加的，源码里没有
        probe = text.removeprefix("[Error]: ")
        if probe not in blob:
            missing.append(text)
    return missing


def main() -> int:
    ap = argparse.ArgumentParser(description="检查后端更新并跑出影响")
    ap.add_argument("--repo", help="后端仓库路径（默认 ~/esa）")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--quiet", action="store_true", help="零影响时不输出，给定时任务用")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser() if args.repo else Path("~/esa").expanduser()
    if not (repo / "backend").exists():
        print(f"❌ {repo} 下没有 backend/ 目录", file=sys.stderr)
        return 2

    out: list[str] = []

    def say(s: str = "") -> None:
        out.append(s)

    try:
        base = baseline_commit()
        run(["git", "fetch", "--quiet", "origin", args.branch], cwd=repo)
        remote = f"origin/{args.branch}"
        head = run(["git", "rev-parse", "--short", remote], cwd=repo)

        log = run(
            ["git", "log", "--oneline", "--no-decorate", f"{base}..{remote}"], cwd=repo
        )
        # 报错文案登记表要每次都核 —— 后端删掉一句文案不会体现在缓存 diff 里，
        # 因为那些文案根本不在缓存里，是写在种子库的登记表里的。
        stale = check_error_registry(repo)
        if stale:
            say("🔴 登记表里这些报错文案**后端源码里已经没有了**：")
            for t in stale:
                say(f"     {t!r}")
            say("   引用它们的样本正在教模型识别线上不会出现的文案。")
            say("   去 seeds/tool_errors.yaml 的 registry 段删掉，并改掉对应样本。")
            say()

        if not log:
            if not args.quiet or stale:
                if not log:
                    print(f"✅ 后端无更新（基线 {base} 已是 {remote} 最新）")
                print("\n".join(out))
            return 1 if stale else 0

        commits = log.splitlines()
        say(f"后端有 {len(commits)} 个新提交：{base} → {head}")
        say()
        for line in commits[:20]:
            say(f"  {line}")
        if len(commits) > 20:
            say(f"  …… 另有 {len(commits) - 20} 个")
        say()

        files = run(
            ["git", "diff", "--name-only", f"{base}..{remote}"], cwd=repo
        ).splitlines()
        hits = sorted(
            {label for f in files for pat, label in TRIGGER_HINTS if pat in f}
        )
        say(f"改动 {len(files)} 个文件；触及关注面：{('、'.join(hits)) if hits else '（无）'}")
        say("⚠️ 以上只是提示，**判定看下面的缓存 diff** —— commit message 和文件名都骗过人。")
        say()

        # 上游动了**我们自己的文件**吗
        # ------------------------------
        # 这是 2026-08-17 补的，补的是一个被证实过、且瞒了三天的盲区：
        #
        # 下面那套「跑 capture 再比缓存」用的是**我们自己的 capture 脚本**。
        # 如果脚本本身抓错了层，它在新旧后端上都会抓出同样的（错的）东西，
        # 于是永远报「零影响」—— 5.24 就是这么发生的：`ContextComposer`
        # 2026-08-14 就上线了，我们的提示词少了三段，而这个工具连续报了三天绿。
        #
        # 破法是找一个**不经过我们 capture** 的信号。最直接的就是：
        # 上游有没有动 `backend/scripts/dataset/` 底下的东西 —— 那是我们的代码。
        # 别人改我们的文件，只可能是两种情况，两种都必须人来看：
        #   1. 他们发现并修了我们的 bug（5.24 就是）
        #   2. 他们为了自己的需要改了我们的东西，可能与我们的用法冲突
        #
        # ⚠️ 而且这直接关系到发布：我们是**整目录拖到网页上传**的，
        # 不合并就会把别人的改动静默覆盖掉（交接文档第十节记过一次）。
        our_files = sorted(f for f in files if f.startswith(OUR_FILES_PREFIX))
        if our_files:
            say(f"🔴 上游改了 {len(our_files)} 个**我们自己的文件**：")
            for f in our_files:
                say(f"    {f[len(OUR_FILES_PREFIX):]}")
            say()
            say("   这不经过下面的缓存 diff —— 缓存全绿也**不代表**没事。")
            say("   必须逐个三方合并，别整目录覆盖：")
            say(f"     git -C {repo} show {base}:<路径>      > /tmp/base")
            say(f"     git -C {repo} show {remote}:<路径>    > /tmp/theirs")
            say("     git merge-file -p dataset/<路径> /tmp/base /tmp/theirs > /tmp/merged")
            say("   合完再跑本工具确认缓存，然后才谈上传。")
            say()

        # 临时 worktree 检出 origin/main，不动用户的工作区
        tmp = Path(tempfile.mkdtemp(prefix="esa_bk_"))
        wt = tmp / "wt"
        capdir = tmp / "cap"
        capdir.mkdir(parents=True)
        try:
            run(["git", "worktree", "add", "--detach", str(wt), remote], cwd=repo)
            say(f"跑 {len(CAPTURES)} 个 capture"
                "（临时 worktree，不动 ~/esa，也不覆盖 data/cache/）……")
            say()

            changed: list[str] = []
            for name, (script, relpath, actions) in CAPTURES.items():
                target = capdir / f"{name}.json"
                r = subprocess.run(
                    [sys.executable, str(Path(__file__).parent / script),
                     "--repo", str(wt), "--out", str(target)],
                    capture_output=True, text=True,
                )
                if r.returncode != 0 or not target.exists():
                    say(f"  {name:16} ❌ capture 失败")
                    say("     " + (r.stderr.strip().splitlines() or ["(无输出)"])[-1])
                    changed.append(name)
                    continue
                same = diff_cache(ROOT / relpath, target)
                say(f"  {name:16} {'相同 ✅' if same else '有变化 ❌'}")
                if not same:
                    changed.append(name)
                    for a in actions:
                        say(f"     → {a}")
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                           cwd=repo, capture_output=True)
            shutil.rmtree(tmp, ignore_errors=True)

        say()
        if our_files:
            say("结论：**上游改了我们的文件，必须人来合**（见上）。")
            if changed:
                say(f"        另有 {len(changed)} 份缓存也变了：{', '.join(changed)}")
            else:
                say("        缓存本身没变 —— 但这**不代表**没事，理由见上面那段。")
            print("\n".join(out))
            return 1
        if not changed:
            say("结论：**零影响**，不需要重新生成数据。")
            say(f"把基线推到 {head}（只更新 _meta，内容不变）：")
            for _name, (script, _relpath, _actions) in CAPTURES.items():
                say(f"  python3 dataset/tools/{script}")
            say("  ⚠️ capture_parser_golden.py 拿 data/ir 当输入，必须排在生成器之后；")
            say("     纯推基线（内容不变）时按上面顺序跑就行。")
            if args.quiet:
                return 0
            print("\n".join(out))
            return 0

        say(f"结论：**{len(changed)} 份缓存变了，需要动手**（{', '.join(changed)}）。")
        say("按交接文档第七节：先跑三个 capture → 跑生成器 → capture_parser_golden → 校验。")
        print("\n".join(out))
        return 1

    except Exception as e:  # noqa: BLE001
        print(f"❌ 检查失败：{e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
