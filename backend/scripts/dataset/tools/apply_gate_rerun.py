#!/usr/bin/env python3
"""🖥️ **集群上跑（要起服务）。** 把闸门真的挂上去跑一遍，量它端到端的效果。

为什么必须真跑一遍
------------------
`steer/README.md` 里那句「FPR 30.5% → 8.5%」是**算出来的，不是跑出来的**：
我拿离线的投影值数了数「哪些会被挡下」，然后假设**挡下之后模型会给出一个
正确的不调用回答**。这一步假设没有验过。

真挂上闸门时，被压制的那一刻模型得改写别的东西 —— 那段话可能不对、可能跑题、
可能格式坏掉。**「不调工具」和「答对」是两件事**，而判分器判的是后者。
所以在把默认值从「不启用」改成「启用」之前，必须真跑一遍再看那张表。

代价很小：阈值 −3.354 下 440 道里**只有 18 道会真的改变**
（14 道误触发被挡下、4 道正常调用被误压），其余 62 道本来就没调工具，压不压一个样。

怎么模拟「被压制」
------------------
⚠️ **`tool_choice="none"` 用不了**：llamafactory 的 API **收下这个字段但不执行**，
模型照样发起调用（94618 当场抓到，脚本拒绝把空回答写进去）。

所以改成**两种都跑**，因为两种都不完美、而偏差方向相反：

    no_tools  把 tools 置空 —— schema 整段从提示里没了，上下文比线上**少**一块
    instruct  schema 留着，另加一句「本轮不要调用工具」—— 上下文比线上**多**一句

真闸门是「schema 在、也不加话，只是不许发起调用」，落在这两者中间。
**两边跑出来的十二项接近，结论才算不挑模拟方式；差得远就只能报区间。**

用法
----
    python tools/apply_gate_rerun.py --endpoint http://127.0.0.1:8000/v1 \\
        --model esa-nothink_ep10 --ids /tmp/suppress_ids.txt \\
        --pred-in  $HOME/esa_results/pred_nothink_ep10_94275.jsonl \\
        --pred-out $HOME/esa_results/pred_nothink_ep10_gated.jsonl
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from esa.eval import SUITES, build_messages, call_endpoint  # noqa: E402
from esa.paths import in_dataset  # noqa: E402


MODES = {
    # 🔴 两种都跑，因为**两种都不完美**，而它们的偏差方向相反：
    #   no_tools  把工具 schema 整段从提示里拿掉 —— 模型不知道有工具，
    #             上下文比线上少了一大块
    #   instruct  schema 留着，多加一句「本轮别调工具」—— 上下文比线上多了一句
    # 真闸门是「schema 在、也不加话，只是不许发起调用」，落在这两者中间。
    # 两种跑出来的十二项如果接近，结论就对模拟方式不敏感；差得远就只能说区间。
    #
    # ⚠️ `tool_choice="none"` 试过了：llamafactory 的 API **收下这个字段但不执行**，
    #    模型照样发起调用（94618 当场抓到）。所以不用它。
    "no_tools": "把 tools 置空",
    "instruct": "保留 tools，另加一句「本轮不要调用工具，直接回答」",
}


def _suppressed(endpoint: str, model: str, msgs: list[dict], tools: list,
                mode: str) -> str:
    """模拟「闸门判定不该调」之后模型该写什么。"""
    if mode == "no_tools":
        return call_endpoint(endpoint, model, msgs, [])
    # ⚠️ 别新起一条 user 消息：`build_messages` 切到「模型该出手」那一刻，
    #    末条本来就常常是 user，再追加一条就成了连续两个 user，
    #    服务端直接 400（94624 当场抓到）。改成**并进末条**。
    m = [dict(x) for x in msgs]
    tip = "\n\n（本轮不要调用任何工具，请直接回答。）"
    if m and m[-1].get("role") == "user":
        m[-1]["content"] = (m[-1].get("content") or "") + tip
    else:
        m.append({"role": "user", "content": tip.strip()})
    return call_endpoint(endpoint, model, m, tools)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--ids", required=True, help="要压制的题号，一行一个")
    ap.add_argument("--pred-in", required=True)
    ap.add_argument("--pred-out", required=True)
    ap.add_argument("--suite", default="main", choices=list(SUITES))
    a = ap.parse_args()

    want = {x.strip() for x in pathlib.Path(a.ids).read_text(encoding="utf-8").split() if x.strip()}
    path = in_dataset("data/eval") / SUITES[a.suite]["eval"]
    recs = {json.loads(x)["gold"]["id"]: json.loads(x)
            for x in path.read_text(encoding="utf-8").splitlines() if x.strip()}
    missing = want - set(recs)
    if missing:
        sys.exit(f"❌ 这些题号不在 {a.suite} 里：{sorted(missing)[:5]}")
    print(f"要重新生成 {len(want)} 道 × {len(MODES)} 种模拟方式（其余原样抄过去）", flush=True)

    src = [json.loads(x) for x in pathlib.Path(a.pred_in).read_text(encoding="utf-8").splitlines()
           if x.strip()]
    for mode, desc in MODES.items():
        print(f"\n──── {mode}：{desc} ────", flush=True)
        rows, n = [], 0
        for row in src:
            rid = row.get("id")
            if rid is None or rid not in want:
                rows.append(row)
                continue
            rec = recs[rid]
            raw = _suppressed(a.endpoint, a.model, build_messages(rec),
                              json.loads(rec["tools"]), mode)
            if not raw.strip():
                sys.exit(f"❌ {rid} 压制后拿到空回答（{mode}）—— 空预测判分时算格式不合法，"
                         "会把跑分压低而且不是模型的问题。先查服务端再重跑。")
            rows.append({"id": rid, "raw": raw, "_gated": mode})
            n += 1
            if n % 6 == 0:
                print(f"  {n}/{len(want)}", flush=True)
        out = pathlib.Path(f"{a.pred_out}.{mode}.jsonl")
        out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                       encoding="utf-8")
        print(f"  ✅ {n} 道 → {out}")
    print("\n⚠️ 两种都不是真闸门（真闸门是 schema 在、也不加话、只是不许发起调用）——"
          "它们的偏差方向相反，两边数接近才说明结论不挑模拟方式。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
