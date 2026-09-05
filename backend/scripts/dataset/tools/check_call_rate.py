#!/usr/bin/env python3
"""训后速检：模型是不是变得「不敢调工具」了。

为什么要单独有这一步
--------------------
2026-09-05 的 94821：DPO 训完直接上了 440 道考卷，跑了 **3 小时 50 分**才知道
模型塌了 —— 调用率 40.9%→9.3%、漏调 5.9%→75.7%、工具选择 81.1%→20.7%。
这个塌陷用 `probe_tool`（383 道，不用人工裁定）**十几分钟就能看出来**。

🔴 而且只看 `probe` 会得到相反的结论。`esa/eval.py:73` 08-26 就写清楚了：

    probe 只有不调用类，测不出「模型变得不敢调工具了」——
    那种退化在 probe 上反而显示为**误触发率大幅改善**，看起来是大成功。

94821 的误触发率正是 30.5% → **0.0%**（满分）。所以这个脚本**两套都要跑**，
`probe_tool` 那一侧是主判据。

⚠️ 这不是评测，产出的数字**不进任何报表**（probe/probe_tool 是训练侧样本渲染的）。
   它只回答一个是非题：**行为塌没塌，要不要花 4 小时上考卷。**

⚠️ 这里的「误触发」**和报表里的误触发率 FPR 不是同一个口径**，别拿去对。
   这里是「不该调的题里调了工具的占比」（分母是全部不该调的题）；
   报表 FPR 的分母窄得多。同一份预测下这里印 7.7%、报表印 30.5%，两个都没错。
   要报数就去看 `esa/eval.py` 判出来的那份，不要引用这个脚本的输出。

用法
----
    python tools/check_call_rate.py \\
        --base $HOME/esa_results/pred_probe_tool_nothink_ep10.jsonl \\
        --new  $HOME/esa_results/pred_probe_tool_dpo2.jsonl \\
        --suite probe_tool
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from esa.eval import PARSERS, SUITES  # noqa: E402
from esa.paths import in_dataset  # noqa: E402


def load(path: str) -> dict[str, str]:
    out = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("id"):
            out[r["id"]] = r.get("raw") or ""
    return out


def stats(preds: dict[str, str], recs: dict[str, dict], parse) -> dict:
    n = call = right = 0
    for rid, rec in recs.items():
        if rid not in preds:
            continue
        got = [c.name for c in parse(preds[rid]).tool_calls]
        want = rec["gold"].get("expected_tools") or []
        n += 1
        call += bool(got)
        if want:
            right += bool(got) and got[0] == want[0]
    return {"n": n, "call": call, "right": right}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True, help="基线预测（比如 ep10）")
    ap.add_argument("--new", required=True, help="新模型预测")
    ap.add_argument("--suite", default="probe_tool", choices=list(SUITES))
    ap.add_argument("--max-drop", type=float, default=10.0,
                    help="该调那侧的调用率允许比基线掉几个百分点。"
                         "超了就红 —— 别去上考卷，先查数据。")
    a = ap.parse_args()
    parse = PARSERS["current"]

    path = in_dataset("data/eval") / SUITES[a.suite]["eval"]
    recs = {r["gold"]["id"]: r for r in
            (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip())}
    call_side = {k: v for k, v in recs.items() if v["gold"].get("expected_tools")}
    no_call_side = {k: v for k, v in recs.items() if not v["gold"].get("expected_tools")}

    pb, pn = load(a.base), load(a.new)
    print(f"{a.suite}：{len(recs)} 道（该调 {len(call_side)}，不该调 {len(no_call_side)}）")
    print(f"  基线 {len(pb)} 条预测 / 新模型 {len(pn)} 条")

    rows, verdict = [], 0
    if call_side:
        b, n = stats(pb, call_side, parse), stats(pn, call_side, parse)
        if b["n"] and n["n"]:
            rb, rn = b["call"] / b["n"] * 100, n["call"] / n["n"] * 100
            sb, sn = b["right"] / b["n"] * 100, n["right"] / n["n"] * 100
            rows.append(("🔴 该调那侧·调用率", rb, rn))
            rows.append(("   该调那侧·工具选对", sb, sn))
            if rn < rb - a.max_drop:
                verdict = 1
    if no_call_side:
        b, n = stats(pb, no_call_side, parse), stats(pn, no_call_side, parse)
        if b["n"] and n["n"]:
            rows.append(("   不该调那侧·误触发", b["call"] / b["n"] * 100,
                         n["call"] / n["n"] * 100))

    if not rows:
        print("❌ 两份预测对不上题号，什么都比不了")
        return 1
    print(f"\n  {'指标':<26}{'基线':>8}{'新模型':>10}{'变化':>10}")
    for name, x, y in rows:
        print(f"  {name:<24}{x:>8.1f}%{y:>9.1f}%{y - x:>+9.1f}")

    if verdict:
        print(f"\n❌ 该调那侧的调用率掉了超过 {a.max_drop} 个点 —— **别去上考卷**。")
        print("   这就是 94821 的塌陷模式：DPO 把工具调用整体压掉了。")
        print("   ⚠️ 注意「不该调那侧·误触发」这时候会显示成大幅改善，那不是成绩。")
        print("   回去查 DPO 训练集的两侧平衡（build_dpo_dataset.py 的闸门五）。")
        return 1
    print("\n✅ 调用行为没塌，可以上考卷了。")
    print("   ⚠️ 这只说明「没塌」，不说明「变好了」—— 好不好只有考卷能判。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
