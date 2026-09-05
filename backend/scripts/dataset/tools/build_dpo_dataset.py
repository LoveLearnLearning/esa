#!/usr/bin/env python3
"""把「真实失败」和「带温度采出来的错答」合成一份 DPO 训练集。

为什么要有这一步
----------------
`make_dpo_pairs.py` 只能从 temperature=0 那一遍的失败里挑，
而 ep10 在探针集上已经够好了，一遍下来只有 **33 对**。
2026-08-26 那次 DPO 就是 16 对，结论是「训得进去、训练集外零泛化」——
而 4.3s 复扫查到的有效量级是**一两百对**（ToolGraph 161 对拿到 +16.8%）。
**16 对推不出「不泛化」，那个规模本来就只够记住那 16 条。**

所以这里把两个来源合起来：

    T=0 的真实失败        `make_dpo_pairs.py` 那批（最"硬"，是模型确定会犯的）
    带温度采出来的错答    `sample_negatives.py` 那批（同一批题上它有多容易犯）

两边的 rejected **都是模型自己产出的**，一个字都不是编的。

🔴 五条闸门
-----------
1. **chosen 必须是参考答案本身**，不是我们改写的。改写过的东西不叫「偏好」。
2. **rejected 必须非空、且确实是那一侧的错**（不该调却调了 / 该调却没调或调错）。
   空串当坏答案等于教模型「什么都不说是对的」。
3. **同一道题的 rejected 有上限**（`--max-per-prompt`）。不设的话，
   少数几道特别容易错的题会占掉大半个数据集，DPO 就变成在背那几道。
4. **chosen 和 rejected 不许相同**。相同说明取错了东西。
5. 🆕 **两侧必须都有，且 chosen 侧的工具调用比例要落在 `--balance-band` 里**
   （默认 0.30–0.70）。**这一条是 2026-09-05 那次事故换来的，见下。**

🔴 第 5 条为什么必须存在（94821）
---------------------------------
第一版只收「不该调」那一侧，合出 143 对，**chosen 侧调工具 0%、rejected 侧 100%**。
在那份数据里「调工具」与「坏答案」完全共线，于是 DPO 走了最短的那条路：
**把工具调用整体压下去**。训完在考卷上——

    全局调用率   40.9%  →   9.3%
    漏调率 FNR    5.9%  →  75.7%
    工具选择     81.1%  →  20.7%
    误触发 FPR   30.5%  →   0.0%   ← 这个「达标」正是塌陷的证据，不是成绩

⚠️ **训练指标一个字都没预警**：`rewards/chosen` 2.9832→2.9778 走平、
`rewards/rejected` 只到 −6.667（远不是 08-26 那次 −210 的位移）、
`accuracies` 1.000、`loss` 0.0027。我当时据此判「训练健康」。
**「chosen 概率没掉」和「行为没塌」是两件事** —— 模型完全可以既保住 chosen 的概率，
又把 chosen 里从未出现过的那类 token 整体压低，这两件事在那份数据上毫不冲突。
所以这道闸门只能建在**数据分布**上，靠看训练曲线永远发现不了。

⚠️ 而且 `esa/eval.py:73` 的注释里，这个退化模式 08-26 就写清楚了
（「probe 只有不调用类，测不出模型变得不敢调工具」）。`probe_tool` 就是为它建的，
这次却没拿它造对子、也没拿它做训后速检，直接上了 4 小时的考卷。

⚠️ 本脚本只负责合，不负责判断这一对该不该用。`gold` 本身可能有问题，
而 DPO 优化的是「相对偏好」不是「正确答案」。落盘前会印分布，**过一眼再训**。
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from esa.eval import PARSERS, SUITES  # noqa: E402
from esa.paths import in_dataset  # noqa: E402

NO_CALL = {"DIRECT_ANSWER", "ASK_USER", "REFUSE"}

# 模型发起工具调用时实际吐出来的壳子。**别改成别的写法** ——
# `_render_call()` 落盘前会拿判分器自己的解析器验一遍，对不上就退出。
CALL_OPEN, CALL_CLOSE = "<tool_call>\n", "\n</tool_call>"


def gold_reply(rec: dict) -> str:
    """给定轮次之后、模型该输出的那一条 —— 这道题的参考答案。

    🔴 两侧取的**不是同一种轮次**：

        不该调的题  取第一条 `gpt`
        该调的题    取第一条 `function_call`，并渲染成模型实际输出的壳子

    ⚠️ 这个分叉是 2026-09-05 验出来的，第一版没有。原来的写法只找 `gpt`/`assistant`，
       在「该调工具」的题上会**跳过 `function_call` 轮**，取到它后面那条
       「工具跑完之后的总结」。拿那个当 chosen，等于教模型
       「该调工具的时候直接编一段总结」—— 比 94821 塌得还狠，而且看起来一切正常。
       174 道该调的题实测：旧写法解析出工具调用 **0** 条（94 条取到总结、80 条取空）。

    ⚠️ `n_turns_given` 的单位是 **conversations 的条数**，不是 human 轮数 ——
       `esa/eval.py:build_messages` 里就是 `rec["conversations"][:n]`。
       旧写法数的是 human 轮，在单轮题上恰好等价，多轮题上会错位
       （`s002_修改参数_0000`：given=3，而 function_call 前只有 2 条 human，
       于是 `seen >= given` 永不成立，静默返回空串）。
    """
    n = rec["gold"].get("n_turns_given", 1)
    want_call = bool(rec["gold"].get("expected_tools"))
    for turn in rec.get("conversations", [])[n:]:
        frm = turn.get("from")
        if want_call and frm == "function_call":
            return _render_call(turn.get("value", ""))
        if not want_call and frm in ("gpt", "assistant"):
            return turn.get("value", "")
        if frm in ("human", "user"):
            break        # 轮到用户说话了还没找到，这道题取不出参考答案
    return ""


def _render_call(value: str) -> str:
    """把 `function_call` 轮的 JSON 包成模型实际输出的样子。

    数据里存的是 `{"name": ..., "arguments": {...}}`，而模型吐的是
    `<tool_call>\n{同一个 JSON}\n</tool_call>` —— 这个壳子不是看预测猜的，
    是 `esa/eval.py:build_messages` 回填历史轮工具调用时用的同一个写法。DPO 的 chosen/rejected 都是裸字符串、
    不走模板的 function_call 渲染，所以这一层得我们自己补上 ——
    补错了 chosen 和 rejected 就不在同一个空间里，偏好对没有意义。
    """
    v = (value or "").strip()
    if not v:
        return ""
    if v.startswith(CALL_OPEN.strip()):   # 已经是渲染好的，别包两层
        return v
    return f"{CALL_OPEN}{v}{CALL_CLOSE}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--suite", default="probe", choices=list(SUITES))
    ap.add_argument("--pred", action="append", default=[],
                    help="temperature=0 的预测文件，可给多份")
    ap.add_argument("--neg", action="append", default=[],
                    help="sample_negatives.py 的产物，可给多份")
    ap.add_argument("--suite-tool", default="probe_tool", choices=list(SUITES),
                    help="该调工具那一侧的题从哪套来")
    ap.add_argument("--max-per-prompt", type=int, default=3)
    ap.add_argument("--balance-band", default="0.30,0.70",
                    help="chosen 侧调工具比例的容许区间。落在外面直接拒绝落盘 —— "
                         "理由见文件头「第 5 条为什么必须存在」。")
    ap.add_argument("--out", help="不给就只印统计、不落盘")
    a = ap.parse_args()
    parse = PARSERS["current"]

    # 🔴 两套题都读进来，一道题属于哪一侧由 `expected_tools` 是否非空决定
    #    （与 esa/eval.py:791 同口径；看 expected_action 字符串会漏掉
    #     RECOVER_TOOL_ERROR 整一类）。
    recs: dict[str, dict] = {}
    for suite in dict.fromkeys([a.suite, a.suite_tool]):
        path = in_dataset("data/eval") / SUITES[suite]["eval"]
        n = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            rid = r["gold"]["id"]
            if rid in recs:
                sys.exit(f"❌ 题号 {rid} 在两套题里都出现了 —— 两套必须互不相交，"
                         "否则同一道题会被当成两侧各来一次")
            recs[rid] = r
            n += 1
        print(f"{suite}：{n} 道")
    n_call = sum(1 for r in recs.values() if r["gold"].get("expected_tools"))
    print(f"合计 {len(recs)} 道 —— 该调 {n_call}，不该调 {len(recs) - n_call}")

    def is_bad(raw: str, rec: dict) -> bool:
        """这条回答算不算「模型自己犯的错」—— 两侧的判据不是同一个。

        与 `tools/sample_negatives.py:_is_bad` 保持一致：

            不该调（expected_tools 空）  调了工具就是错
            该调                        没调、或第一个工具名对不上就是错
        """
        if not raw.strip():
            return False          # 空回答当 rejected 等于教「什么都不说是对的」
        got = [c.name for c in parse(raw).tool_calls]
        want = rec["gold"].get("expected_tools") or []
        if not want:
            return bool(got)
        return (not got) or got[0] != want[0]

    # rid -> list[(rejected_raw, 来源)]
    bad: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    for files, src in ((a.pred, "T=0"), (a.neg, "采样")):
        for f in files:
            n = skipped = 0
            for line in pathlib.Path(f).read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                rid = row.get("id")
                if rid is None:
                    continue          # `_meta` 那一行
                if rid not in recs:
                    skipped += 1
                    continue
                raw = row.get("raw") or ""
                if is_bad(raw, recs[rid]):
                    bad[rid].append((raw, src))
                    n += 1
            label = "真实失败" if src == "T=0" else "采样错答"
            tail = f"（{skipped} 条题号不在这两套题里，跳过）" if skipped else ""
            print(f"  {pathlib.Path(f).name}：{label} {n} 条{tail}")

    pairs, dropped = [], collections.Counter()
    for rid, items in sorted(bad.items()):
        rec = recs[rid]
        chosen = gold_reply(rec)
        if not chosen.strip():
            dropped["没有参考答案"] += len(items)
            continue
        seen: set[str] = set()
        kept = 0
        for raw, src in items:
            if kept >= a.max_per_prompt:
                dropped["同题超过上限"] += 1
                continue
            if raw in seen:
                dropped["同题内重复"] += 1
                continue
            if raw.strip() == chosen.strip():
                dropped["与参考答案相同"] += 1
                continue
            seen.add(raw)
            kept += 1
            # 🔴 与 `esa/eval.py:build_messages` 同一个口径：`n_turns_given` 是
            #    **conversations 的条数**，直接切片。旧写法按 human 轮计数，
            #    多轮题上 `n_h >= given` 永不成立 → 整段 conversations 都被带上，
            #    **连答案本身一起**，而且条数变偶数。
            #    LLaMA-Factory 的两条硬要求（`data/converter.py:144-175` 核过）：
            #      ① 角色严格交替 —— 奇数位 user/observation、偶数位 assistant/function_call
            #      ② `ranking: true` 时条数必须是**奇数**，偶数当场判 broken_data 丢弃
            #    切片天然满足两条，因为 `n_turns_given` 就切在「模型该出手」那一刻。
            convs = rec["conversations"][:rec["gold"].get("n_turns_given", 1)]
            pairs.append({
                "_id": rid, "_src": src,
                "_side": "call" if rec["gold"].get("expected_tools") else "no_call",
                "_template_id": rec["gold"].get("template_id"),
                "_expected_action": rec["gold"]["expected_action"],
                "_wrong_tool": [c.name for c in parse(raw).tool_calls],
                "system": rec["system"], "tools": rec["tools"],
                "conversations": convs,
                "chosen": {"from": "gpt", "value": chosen},
                "rejected": {"from": "gpt", "value": raw},
            })

    print(f"\n合成 {len(pairs)} 对，覆盖 {len({p['_id'] for p in pairs})} 道题")
    print("  来源：", dict(collections.Counter(p["_src"] for p in pairs)))
    print("  两侧：", dict(collections.Counter(p["_side"] for p in pairs)))
    print("  行为：", dict(collections.Counter(p["_expected_action"] for p in pairs)))
    top = collections.Counter(p["_id"] for p in pairs).most_common(3)
    print(f"  单题最多的三道：{top}（上限 {a.max_per_prompt}）")
    if dropped:
        print("  丢掉：", dict(dropped))
    if not pairs:
        print("❌ 一对都没合出来")
        return 1

    # ── 🔴 闸门五：两侧必须都有，chosen 侧的工具调用比例要落在带内 ──
    # 这道闸门建在**数据分布**上而不是训练曲线上，因为 94821 那次训练曲线
    # 从头到尾都正常（详见文件头）。
    n_ch = sum(1 for q in pairs if parse(q["chosen"]["value"]).tool_calls)
    n_rj = sum(1 for q in pairs if parse(q["rejected"]["value"]).tool_calls)
    lo, hi = (float(x) for x in a.balance_band.split(","))
    r_ch, r_rj = n_ch / len(pairs), n_rj / len(pairs)
    print(f"\n  chosen   侧调工具：{n_ch}/{len(pairs)} = {r_ch:.1%}")
    print(f"  rejected 侧调工具：{n_rj}/{len(pairs)} = {r_rj:.1%}")
    if not lo <= r_ch <= hi:
        print(f"\n❌ 闸门五：chosen 侧调工具比例 {r_ch:.1%} 不在 [{lo:.0%}, {hi:.0%}] 内。")
        print("   「调工具」与「好/坏答案」在这份数据里共线，DPO 会去压整个调用行为，"
              "而不是学会「什么时候别调」。")
        print("   94821 就是这么塌的：调用率 40.9%→9.3%、漏调 5.9%→75.7%，"
              "而训练曲线全程正常。")
        print(f"   补另一侧的对子再来（--side {'call' if r_ch < lo else 'no_call'} 那一侧不够）。")
        return 1
    print(f"  ✅ 闸门五：chosen 侧比例落在 [{lo:.0%}, {hi:.0%}] 内")

    if not a.out:
        print("\n（没给 --out，只统计不落盘。过一眼再加 --out）")
        return 0
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in pairs) + "\n",
                   encoding="utf-8")
    print(f"\n✅ → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
