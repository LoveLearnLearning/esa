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

🔴 两侧都要采（`--side`），而且必须都采
--------------------------------------
第一版只在「不该调」那侧采，理由写的是「那边的错是另一种错，混进同一批偏好对
会把目标搅浑」。**那个理由是错的，代价是 2026-09-05 的 94821。**

只采不该调那侧，合出来的 143 对里 `chosen` 侧调工具 **0%**、`rejected` 侧 **100%** ——
「调工具」和「坏答案」在训练集里完全共线。DPO 会走最短的那条路：
**把所有工具调用 token 的概率整体压下去**，而不是「在这些情况下别调」。
实测后果是全局调用率 40.9% → 9.3%、漏调率 5.9% → 75.7%
（而误触发率「改善」到 0.0% —— 那个漂亮数字正是塌陷的证据）。

所以：

    --side no_call  不该调的题（expected_tools 为空），留下**调了工具**的采样
    --side call     该调的题（expected_tools 非空），留下**没调或调错**的采样

两侧的产物一起喂给 `build_dpo_dataset.py`，让「调工具」在 chosen 侧也大量出现。
那个脚本落盘前会硬查这个比例，不平衡就拒绝落盘。

⚠️ 该不该调看 `expected_tools` 是否非空，**不看 `expected_action` 字符串** ——
   与 `esa/eval.py:791` 同一个口径。用字符串会把 RECOVER_TOOL_ERROR
   （读懂报错、改对参数再调一次）整类漏掉。

⚠️ 采样是有温度的，所以**这份产物不可复现**（和评测不同）。
   它只用来造训练数据，**绝不能拿去报任何指标**。落盘时会写进 meta。

用法
----
    python tools/sample_negatives.py --endpoint http://127.0.0.1:8000/v1 \\
        --model esa-nothink_ep10 --suite probe --side no_call \\
        --n 4 --temperature 0.9 --out $HOME/esa_results/neg_probe_ep10.jsonl

    python tools/sample_negatives.py --endpoint http://127.0.0.1:8000/v1 \\
        --model esa-nothink_ep10 --suite probe_tool --side call \\
        --n 4 --temperature 0.9 --out $HOME/esa_results/neg_probe_tool_ep10.jsonl
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

def _is_bad(parsed, want_tools: list[str], side: str) -> bool:
    """这条采样算不算「模型自己犯的错」—— 也就是能不能当 rejected。

    两侧的「错」不是同一件事：

        no_call  不该调却调了            → 有 tool_calls 就是错
        call     该调却没调、或调错了工具 → 没有 tool_calls，或第一个名字对不上

    ⚠️ `call` 侧只看**工具名**，不看参数。参数错也是错，但那是另一个维度，
       混进来会让偏好对的信号变糊 —— 我们这一批要压的是「调不调、调哪个」。
    """
    got = [c.name for c in parsed.tool_calls]
    if side == "no_call":
        return bool(got)
    return (not got) or got[0] != want_tools[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--suite", default="probe", choices=list(SUITES))
    ap.add_argument("--side", required=True, choices=["no_call", "call"],
                    help="采哪一侧的错。**两侧都要采**，理由见文件头。")
    ap.add_argument("--n", type=int, default=4, help="每道题采几次")
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--out", required=True)
    ap.add_argument("--parser", default="current", choices=list(PARSERS))
    a = ap.parse_args()
    parse = PARSERS[a.parser]

    path = in_dataset("data/eval") / SUITES[a.suite]["eval"]
    recs = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    # 🔴 用 `expected_tools` 非空判定该不该调，与 esa/eval.py:791 同口径。
    #    看 `expected_action` 字符串会漏掉 RECOVER_TOOL_ERROR 整一类。
    want_call = a.side == "call"
    recs = [r for r in recs if bool(r["gold"].get("expected_tools")) == want_call]
    if not recs:
        print(f"❌ {a.suite} 里一道 side={a.side} 的题都没有 —— 选错套题了。"
              f"（不该调的在 probe，该调的在 probe_tool）")
        return 1
    print(f"{a.suite}：{len(recs)} 道{'该调' if want_call else '不该调'}的题，"
          f"每道采 {a.n} 次（temperature={a.temperature}）", flush=True)

    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    kept = fails = 0
    t0 = time.time()
    with out.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_meta": {
            "note": "带温度采样的产物，**不可复现**，只用来造 DPO 的 rejected，"
                    "绝不能拿去报任何指标",
            "suite": a.suite, "side": a.side, "n": a.n,
            "temperature": a.temperature, "model": a.model,
        }}, ensure_ascii=False) + "\n")
        for i, rec in enumerate(recs, 1):
            tools = json.loads(rec["tools"])
            msgs = build_messages(rec)
            want_tools = rec["gold"].get("expected_tools") or []
            seen: set[str] = set()
            for _ in range(a.n):
                try:
                    raw = call_endpoint(a.endpoint, a.model, msgs, tools,
                                        temperature=a.temperature)
                except Exception as exc:      # noqa: BLE001
                    fails += 1
                    print(f"  ⚠️ {rec['gold']['id']} 采样失败：{exc}", flush=True)
                    continue
                pp = parse(raw)
                if not _is_bad(pp, want_tools, a.side):
                    continue                  # 采对了，不是我们要的
                if not raw.strip():
                    continue                  # 空回答当 rejected 等于教「什么都不说是对的」
                if raw in seen:               # 同一条重复采到，只留一份
                    continue
                seen.add(raw)
                # ⚠️ `pp.tool_calls` 是 `backend_parser.ToolCall` 数据类，不是 dict ——
                #    第一版写了 `c.get("name")`，跑到第一条真调工具的样本上才炸（94610）。
                fh.write(json.dumps({"id": rec["gold"]["id"], "raw": raw,
                                     "side": a.side,
                                     "called": [c.name for c in pp.tool_calls]},
                                    ensure_ascii=False) + "\n")
                kept += 1
            if i % 25 == 0:
                el = time.time() - t0
                print(f"  {i}/{len(recs)}  已捞到 {kept} 条  {el:.0f}s", flush=True)
    what = "该调却没调/调错了" if a.side == "call" else "不该调却调了"
    print(f"\n✅ {len(recs)} 道题采了 {len(recs) * a.n} 次，捞到 {kept} 条「{what}」→ {out}")
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
