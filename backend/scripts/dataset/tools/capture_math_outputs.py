# backend/scripts/dataset/tools/capture_math_outputs.py

"""抓取三个计算器的**线上真实返回值**，落成缓存。

为什么要有这个脚本
------------------
`tools_exec.py` 里的三个计算器原本是我自己重写的一版，返回 `{"value": 44}`。
而后端真实返回的是 `{"expression": "20+4*6", "result": 44}` ——
字段名完全不同，`math_solver` 更是根本没有 `latex` 字段（数据里 22 条回答正是引用它写的）。
模型学会消费一个线上不存在的结构，等于白训。

所以改成和 `arxiv_real.json` 同一套办法：**跑真实实现，把真实输出存下来**，
生成器只查表不计算。缓存本身就是「这些观测值不是编的」的证据，也保证可复现
（赛题《03—技术方案说明》明确要求可复现）。

复刻还是执行？—— 执行。复刻一份代码到本地，下次后端改了实现我们不会知道；
执行真实函数，改了就是改了，重跑一次立刻暴露。

用法
----
    python3 dataset/tools/capture_math_outputs.py                 # 默认用本地 ~/esa
    python3 dataset/tools/capture_math_outputs.py --repo <路径>   # 指定别的副本
    python3 dataset/tools/capture_math_outputs.py --download      # 强制下载快照

⚠️ 只读后端仓库，不改它的任何文件。下载的副本落在临时目录，不入库。

为什么默认改成本地 clone（2026-08-11）
--------------------------------------
tarball 抓的是 GitHub 上那一刻的 main，**抓不到你刚 `git pull` 下来的改动，而且不会报错**。
2026-08-11 后端大改（删 MATH_PRMOPT / Skill 路由 / observation 转 JSON / schema 更新）时
差点就拿旧 schema 对齐了数据。改成默认读 `~/esa`，配合 `git -C ~/esa pull`，
版本关系是你自己看得见的。找不到本地副本才回退下载。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backend_repo  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CALC_SEEDS = ROOT / "dataset/seeds/calculators.yaml"
ERROR_SEEDS = ROOT / "dataset/seeds/tool_errors.yaml"
OUT = ROOT / "dataset/data/cache/math_real.json"

MATH_SOURCES = [
    "backend/agent/tools/math_tools/calculator.py",
    "backend/agent/tools/math_tools/bitwise_calculator.py",
    "backend/agent/tools/math_tools/math_solver.py",
    "backend/agent/tools/math_tools/_base_evaluator.py",
]
TOOLS = ("calculator", "bitwise_calculator", "math_solver")

# observation 序列化的黄金样例。
#
# 后端 2026-08-11 把 `str(result)` 换成了 `json.dumps(result, ensure_ascii=False, default=str)`
# （agent.py:48-54）。这个改动里最容易漏的一处是**返回字符串的工具**：
# `str("北京: 26 摄氏度 晴朗")` 是裸字符串，`json.dumps(...)` 会带上一对双引号。
# load_skill / get_time / get_weather 和全部 `[Error]: ...` 失败观测都走这条路。
#
# 所以这里拿真实的 serialize_tool_result 跑一遍探针值，把结果存下来，
# 由 test_fixture_contract.py 逐条比对 render._serialize_result —— 那条捷径
# 曾经在 `str()` 时代是对的，换格式之后就悄悄错了，而且没有任何校验拦得住。
OBSERVATION_PROBES: list = [
    "北京: 26 摄氏度 晴朗",                    # get_weather 硬编码桩
    "08/11/26-07:00:00",                       # get_time（%D 格式，见 6.3）
    "exam_prediction skill not found!",        # load_skill 失败文案
    "[Error]: division by zero",               # tool_register 的失败表示
    {"expression": "20+4*6", "result": 44},    # calculator 成功
    {"expression": "1/0", "result": None, "error": "division by zero"},  # 内部 None 不许被剪
    {"recommendations": [], "count": 0, "ok": True},                     # 内部 [] 不许被剪
    {"中文键": "中文值"},                       # ensure_ascii=False
    [{"name": "a", "content": 1}, {"name": "b", "content": 2}],          # 并行调用合并形态
]


def cache_key(tool: str, args: dict) -> str:
    """缓存的键。参数排序后序列化，保证同一组参数永远得到同一个键。"""
    return f"{tool}|{json.dumps(args, ensure_ascii=False, sort_keys=True)}"


def source_fingerprint(repo: Path) -> dict[str, str]:
    """三个计算器源文件的 sha256。

    这是最贴切的溯源信息：它钉住的正是产出这些观测值的那段代码。
    指纹一变就说明后端改了实现，缓存必须重抓。
    """
    out = {}
    for rel in MATH_SOURCES:
        p = repo / rel
        if not p.exists():
            raise SystemExit(f"后端仓库里找不到 {rel}，路径可能变了")
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return out


def load_backend_tools(repo: Path):
    """import 真实实现。失败要吵，不要退回本地近似。"""
    sys.path.insert(0, str(repo))
    try:
        mods = {t: importlib.import_module(f"backend.agent.tools.math_tools.{t}") for t in TOOLS}
    except ImportError as exc:
        raise SystemExit(
            f"无法 import 后端 math_tools：{exc}\n"
            "这些模块依赖 requests/sympy，先 pip install 再重试。"
            "注意不要改用本地实现顶替 —— 那正是这次要修掉的问题。"
        ) from exc
    return {t: getattr(mods[t], t) for t in TOOLS}


def capture_observation_format(repo: Path) -> list[dict]:
    """跑后端真实的 serialize_tool_result，把探针值的序列化结果钉下来。"""
    sys.path.insert(0, str(repo))
    try:
        from backend.agent.agent import serialize_tool_result  # noqa: PLC0415
    except ImportError as exc:
        raise SystemExit(
            f"无法 import backend.agent.agent.serialize_tool_result：{exc}\n"
            "observation 的序列化方式必须来自后端真实函数，不要在本地复刻一版。"
        ) from exc
    # 探针原样存，**不要 sort_keys** —— json.dumps 按插入顺序输出，
    # 排过序的键再读回来就不是原来那个 dict 了，比对会假失败。
    # 顺带说明：这也意味着观测的键顺序本身是数据的一部分。
    return [
        {"probe": probe, "expected": serialize_tool_result(probe)}
        for probe in OBSERVATION_PROBES
    ]


def collect_jobs() -> list[tuple[str, dict]]:
    """从种子库里收集所有需要真实执行的调用。"""
    jobs: list[tuple[str, dict]] = []
    seen: set[str] = set()

    def add(tool: str, args: dict) -> None:
        """添加 `add` 相关数据。

        Args:
            tool: str => `tool` 参数。
            args: dict => `args` 参数。
        """
        k = cache_key(tool, args)
        if k not in seen:
            seen.add(k)
            jobs.append((tool, args))

    calc = yaml.safe_load(CALC_SEEDS.read_text(encoding="utf-8"))
    for seed in calc["calculator"]:
        add("calculator", {"expression": seed["expr"]})
    for seed in calc["bitwise_calculator"]:
        add("bitwise_calculator", {"expression": seed["expr"]})
    for seed in calc["math_solver"]:
        args = {"operation": seed["op"], "expression": seed["expr"], "variable": seed["var"]}
        args.update(seed.get("extra") or {})
        add("math_solver", args)

    # skills_rag 里「该调另一个工具」那组也会真调计算器
    sr = ROOT / "dataset/seeds/skills_rag.yaml"
    if sr.exists():
        cfg = yaml.safe_load(sr.read_text(encoding="utf-8")) or {}
        for section in ("load_skill", "rag"):
            for item in (cfg.get(section) or {}).get("混淆_应调其它工具", []):
                if item["tool"] in TOOLS:
                    add(item["tool"], item["args"])

    # tool_error 种子库里的失败调用（以及「改参数重试」那一次修正后的调用）
    if ERROR_SEEDS.exists():
        errs = yaml.safe_load(ERROR_SEEDS.read_text(encoding="utf-8")) or {}
        for item in errs.get("calculators", []):
            add(item["tool"], item["args"])
            if item.get("retry_args") is not None:
                add(item["tool"], item["retry_args"])
    return jobs


def main() -> int:
    """运行当前模块的命令行入口。"""
    ap = argparse.ArgumentParser(description="抓取三个计算器的线上真实返回值")
    ap.add_argument("--repo", help="本地后端仓库副本；默认 ~/esa")
    ap.add_argument("--download", action="store_true", help="强制下载快照（抓不到本地改动，慎用）")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    with backend_repo.resolve(args.repo, download=args.download) as backend:
        repo = backend.path
        fingerprint = source_fingerprint(repo)
        fns = load_backend_tools(repo)
        jobs = collect_jobs()

        entries: dict[str, dict] = {}
        n_err = 0
        for tool, call_args in jobs:
            # 这三个工具**不抛异常**，失败也是正常返回一个带 error 键的 dict
            # （calculator.py:145-150 / bitwise_calculator.py:157-162 / math_solver.py:298-304）。
            # 这一点本身就是要教给模型的：同一个 Agent 里存在两套失败表示。
            result = fns[tool](**call_args)
            entries[cache_key(tool, call_args)] = result
            if isinstance(result, dict) and "error" in result:
                n_err += 1

        payload = {
            "_meta": {
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "github.com/LoveLearnLearning/esa",
                "source_repo": backend.describe(),
                "source_sha256": fingerprint,
                "note": "由 dataset/tools/capture_math_outputs.py 执行后端真实函数产出，禁止手改",
            },
            "entries": entries,
            "observation_format": capture_observation_format(repo),
        }
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        print(f"\n抓到 {len(entries)} 条真实返回（其中 {n_err} 条是失败返回）→ {backend_repo.display_path(out_path, ROOT)}")
        print(f"  来源：{backend.describe()}")
        for rel, h in fingerprint.items():
            print(f"  {h}  {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
