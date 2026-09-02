#!/usr/bin/env python3
"""闸门：`structured_runtime` 种子 ↔ 后端 `execution_errors.py` 必须逐字一致。

为什么要有这道
--------------
`seeds/tool_errors.yaml` 里那 7 条的 `message` 是**后端源码里的字面量**
（`ERROR_MESSAGES` 字典），`retryable` 是 `RETRYABLE_ERROR_CODES` 推导出来的。
上游只要改一个字，我们的种子就静默过期 —— 而模型看见的 observation 会和线上
对不上，`validate` 的 `load_error_registry` 也会认不出那句话。

这是 5.18 / 5.31 / 5.47 那一族的形状：**抓的是模型看得见的那一层，
而那一层随时会被上游改动**。唯一的防法是每次跑一遍对账，别靠人记。

📌 不 import 后端（依赖装不全，5.32 ③），改成从源码正则抠 —— 抠不到就红，
   不静悄悄放行。
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
SEEDS = HERE.parent / "seeds" / "tool_errors.yaml"
CANDIDATES = [
    pathlib.Path.home() / "esa" / "backend" / "agent" / "tools" / "execution_errors.py",
    HERE.parents[3] / "backend" / "agent" / "tools" / "execution_errors.py",
]


def _backend_source() -> pathlib.Path:
    for p in CANDIDATES:
        if p.is_file():
            return p
    sys.exit("❌ 找不到 backend/agent/tools/execution_errors.py —— "
             f"找过：{[str(p) for p in CANDIDATES]}\n"
             "   这道闸门守的是「种子 ↔ 线上文案」，找不到源码就不能放行（5.72）。")


def _parse(src: str) -> tuple[dict[str, str], set[str]]:
    try:
        body = src.split("ERROR_MESSAGES")[1].split("}")[0]
        msgs = dict(re.findall(r'"([a-z_]+)":\s*"([^"]+)"', body))
        rbody = src.split("RETRYABLE_ERROR_CODES")[1].split(")")[0]
        retryable = set(re.findall(r'"([a-z_]+)",', rbody))
    except IndexError:
        sys.exit("❌ 源码结构变了，抠不出 ERROR_MESSAGES / RETRYABLE_ERROR_CODES")
    if not msgs or not retryable:
        sys.exit("❌ 抠出来是空的 —— 正则过期了，别当成「没有错误」")
    return msgs, retryable


def main() -> int:
    src_path = _backend_source()
    msgs, retryable = _parse(src_path.read_text(encoding="utf-8"))
    print(f"对着 {src_path} 核："
          f"ERROR_MESSAGES {len(msgs)} 条 · RETRYABLE {len(retryable)} 条")

    seeds = yaml.safe_load(SEEDS.read_text(encoding="utf-8"))
    items = seeds.get("structured_runtime") or []
    if not items:
        sys.exit("❌ 种子里没有 structured_runtime 段")

    bad = 0
    for it in items:
        code = it["error_code"]
        if code not in msgs:
            print(f"  ❌ {it['id']}：后端没有 error_code={code}")
            bad += 1
            continue
        if it["message"] != msgs[code]:
            print(f"  ❌ {it['id']}：message 对不上\n"
                  f"       种子「{it['message']}」\n       源码「{msgs[code]}」")
            bad += 1
        if bool(it["retryable"]) != (code in retryable):
            print(f"  ❌ {it['id']}：retryable 种子 {it['retryable']}，"
                  f"源码推导 {code in retryable}")
            bad += 1

    uncovered = sorted(set(msgs) - {i["error_code"] for i in items})
    print(f"{len(items)} 条种子核完，{bad} 处不一致")
    # 覆盖率只报，不判不合格：补哪些 error_code 是数据设计决定，不是契约要求。
    print(f"📌 后端 {len(msgs)} 个 error_code 里种子覆盖 {len(items)} 个，"
          f"未覆盖 {len(uncovered)}：{uncovered}")
    if bad:
        print("❌ 种子已过期，重生成之前必须先对齐")
        return 1
    print("✅ structured_runtime 种子与后端源码逐字一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
