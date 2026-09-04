#!/usr/bin/env python3
"""🖥️ **集群上跑（要起服务）。** 在「不该调工具」的题上多采几次，把模型自己犯的错捞出来。

为什么需要它
------------
DPO 的 rejected 要用**模型自己的错答**，而 `make_dpo_pairs.py` 只能从
temperature=0 那一遍的失败里挑。ep10 在探针集上已经够好了，
一遍下来只剩 **33 对**（误触发 20 / 拒绝 11 / 追问 2）——
而 4.3s 复扫查到的量级是「一两百对、且挑在分歧点上」才有实证效果
（ToolGraph 161 对拿到 +16.8%）。**33 对大概率还是不够。**

这个脚本换个采法：同一道题采 N 次、temperature>0，
把**采出来会调工具的那些**留下当 rejected。它们仍然全是模型自己产出的，
一个字都不是编的；只是把「它有多容易犯这个错」采样出来了。

🔴 只在 `expected_action` ∈ {DIRECT_ANSWER, ASK_USER, REFUSE} 的题上采。
   该调工具的题不采 —— 那边的错是另一种错，混进同一批偏好对会把目标搅浑。

⚠️ 采样是有温度的，所以**这份产物不可复现**（和评测不同）。
   它只用来造训练数据，**绝不能拿去报任何指标**。落盘时会写进 meta。

用法
----
    python tools/sample_negatives.py --endpoint http://127.0.0.1:8000/v1 \\
        --model esa-nothink_ep10 --suite probe \\
        --n 4 --temperature 0.9 --out $HOME/esa_results/neg_probe_ep10.jsonl
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from esa.eval import PARSERS, SUITES, build_messages, call_endpoint  # noqa: E402
from esa.paths import in_dataset  # noqa: E402

NO_CALL = {"DIRECT_ANSWER", "ASK_USER", "REFUSE"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--suite", default="probe", choices=list(SUITES))
    ap.add_argument("--n", type=int, default=4, help="每道题采几次")
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--out", required=True)
    ap.add_argument("--parser", default="current", choices=list(PARSERS))
    a = ap.parse_args()
    parse = PARSERS[a.parser]

    path = in_dataset("data/eval") / SUITES[a.suite]["eval"]
    recs = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    recs = [r for r in recs if r["gold"]["expected_action"] in NO_CALL]
    print(f"{a.suite}：{len(recs)} 道不该调的题，每道采 {a.n} 次 "
          f"（temperature={a.temperature}）", flush=True)

    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    kept = fails = 0
    t0 = time.time()
    with out.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_meta": {
            "note": "带温度采样的产物，**不可复现**，只用来造 DPO 的 rejected，"
                    "绝不能拿去报任何指标",
            "suite": a.suite, "n": a.n, "temperature": a.temperature,
            "model": a.model,
        }}, ensure_ascii=False) + "\n")
        for i, rec in enumerate(recs, 1):
            tools = json.loads(rec["tools"])
            msgs = build_messages(rec)
            seen: set[str] = set()
            for _ in range(a.n):
                try:
                    raw = call_endpoint(a.endpoint, a.model, msgs, tools,
                                        temperature=a.temperature)
                except Exception as exc:      # noqa: BLE001
                    fails += 1
                    print(f"  ⚠️ {rec['gold']['id']} 采样失败：{exc}", flush=True)
                    continue
                p = parse(raw)
                # 只留「采出来调了工具」的 —— 那才是我们要压的那种错。
                if not p.tool_calls:
                    continue
                if raw in seen:               # 同一条重复采到，只留一份
                    continue
                seen.add(raw)
                # ⚠️ `p.tool_calls` 是 `backend_parser.ToolCall` 数据类，不是 dict ——
                #    第一版写了 `c.get("name")`，跑到第一条真调工具的样本上才炸（94610）。
                fh.write(json.dumps({"id": rec["gold"]["id"], "raw": raw,
                                     "called": [c.name for c in p.tool_calls]},
                                    ensure_ascii=False) + "\n")
                kept += 1
            if i % 25 == 0:
                el = time.time() - t0
                print(f"  {i}/{len(recs)}  已捞到 {kept} 条  {el:.0f}s", flush=True)
    print(f"\n✅ {len(recs)} 道题采了 {len(recs) * a.n} 次，捞到 {kept} 条「不该调却调了」"
          f"→ {out}")
    if fails:
        print(f"⚠️ {fails} 次请求失败（采样容许失败，不影响已捞到的那些；"
              "但失败太多说明服务不稳，看一眼日志）")
    if kept == 0:
        print("❌ 一条都没捞到 —— 要么模型在这套题上已经不犯这个错，"
              "要么 temperature 太低。先查清楚再往下走。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
