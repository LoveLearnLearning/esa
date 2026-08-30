"""SDFT 试点：让 base 把「调完工具后那段总结」用自己的话重写，再过我们的闸门。

    # 🖥️ 本机，只挑样本+拼提示词，不连模型（先看选得对不对）
    python3 dataset/tools/sdft_pilot.py --dry-run

    # 🖥️ 集群，作业里 API 起来之后
    PYTHONPATH=. python tools/sdft_pilot.py \\
        --endpoint http://127.0.0.1:8000/v1 --model esa-base --out data/sdft/pilot.jsonl

为什么做这件事
--------------
2026-08-28 在同一套考卷上量了三个模型「开口时说多长」：

| 类别 | base | 80269 | 85362 |
|---|---|---|---|
| RESPOND_TOOL_RESULT | **395** | 54 | 70 |
| DIRECT_ANSWER | **299** | 44 | 37 |

**base 会写，是我们训短的。** 而我们自己那 512 条没被「回答控制在 3 句内」
写过的样本中位 **281 字**，与 base 的 299 几乎重合 —— 这个任务的自然长度
就是 280~300，是另外 913 条被压到了 39（5.63 / 5.66）。

方法叫 **SDFT**（Self-Distillation Fine-Tuning，ACL 2024，arXiv 2402.13669，
代码 sail-sg/sdft）：灾难性遗忘的根因是「任务数据集分布」与「种子模型分布」
的差距，做法是让种子模型把 gold 用自己的话重写、当作新的训练目标。
它的头号实验恰好是工具调用数据集 OpenFunctions：普通微调让 HumanEval
pass@1 从 13.4 掉到 9.8（−27%），SDFT 反而升到 15.2。

我们比论文那个设置强在**筛子**：他们用简单启发式，我们有十二项判分器
和忠实度的配对校验（编数字当场抓）。

三条不许越过的线
----------------
1. 🔴 **只重写最后那段散文。** 工具调用与观测值全部固定（teacher forcing）——
   base 的工具选择只有 38.8%，`ASK_USER` 那 1206 字更是「该追问却在长篇大论」。
   **那些长文本是错误行为的产物，绝不能当目标。**
2. 🔴 **只挑「该展开却很短」的族。** 算术、天气、保存确认本来就该短（5.68：
   用「短」筛出来的清单，一半是本来就该短的）。
3. 🔴 **验收按结构不按字数。** 拿字数当筛选标准就是在训练算法利用长度偏置
   （arXiv 2406.17744）。字数只当观测量。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa.backend_parser import PARSERS  # noqa: E402
from esa.eval import call_endpoint, observation_entities, unsupported_numbers  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# 「该展开却很短」的族。数字是 2026-08-28 实测的末轮 assistant 中位字数。
TARGET_FAMILIES = {
    "record_learning_evidence": 37,
    "get_review_timing": 43,
    "get_mastery_level": 54,
    "get_weak_prerequisites": 67,
    "search_core_memories": 93,
}
# 本来就该短的，别碰（5.68 逐条过眼验证过）。列出来是为了让「为什么不选它」可查。
CORRECTLY_SHORT = {
    "calculator": "报个算式结果就完了", "bitwise": "同上", "math_solver": "同上",
    "time": "报个时间", "weather": "报个天气", "run_in_sandbox": "报个 stdout",
    "mem": "保存/删除确认，长了反而啰嗦",
}

REWRITE_TMPL = """下面是一段真实对话，以及一个【参考回答】。请把参考回答改写成你自己的话。

[对话]
用户：{user}

你调用了工具：{call}

工具返回：
{observation}

[参考回答]
{ref}

[改写要求]
1. **语义等价**：不得引入参考回答里没有的结论、建议或承诺。
2. **不得编造数字**：只能使用「工具返回」和「用户原话」里出现过的数值。
3. 按 system prompt 的风格要求来：先给结论；复杂问题按需展开，保留必要的
   步骤、依据和结论；不为凑短而省略关键信息。
4. 工具返回里有而参考回答没用上的**有效信息**，可以补进去（例如变化量、
   活动类型、下一步该做什么），但仍受第 2 条约束。
5. 直接输出改写后的回答本身，不要加标题、不要解释你做了什么。"""


def load_ir() -> list[dict]:
    out = []
    for f in sorted((ROOT / "dataset/data/ir").glob("*.jsonl")):
        out += [json.loads(x) for x in f.open(encoding="utf-8") if x.strip()]
    return out


def train_pool_ids() -> set[str]:
    """只重写训练池里的样本 —— 考卷里的一个字都不许动。"""
    p = ROOT / "dataset/data/eval/train_ir.jsonl"
    if not p.exists():
        raise SystemExit(f"❌ {p} 不在。先跑 `python -m esa.evalset`。")
    ids = {json.loads(x)["id"] for x in p.open(encoding="utf-8") if x.strip()}
    if not ids:
        raise SystemExit("❌ train_ir 里一个 id 都没读到（5.22：扫出 0 先验扫描本身）")
    return ids


def candidates(n: int) -> list[dict]:
    """按族轮转取样，每族取最短的那些 —— 不是全局取最短。

    全局取最短会让 30 条全是 `record_learning_evidence`（它中位才 37），
    试点就只验到了一个族。轮转取样这条是 5.19 立的规矩。
    """
    pool = train_pool_ids()
    by_fam: dict[str, list[dict]] = defaultdict(list)
    for s in load_ir():
        turns = s["turns"]
        if s["id"] not in pool:
            continue
        if len(turns) < 2 or turns[-1].get("role") != "assistant":
            continue
        obs = [t for t in turns[:-1] if t.get("role") == "tool_result"]
        if not obs:
            continue
        fam = s["template_id"].split("__")[0]
        if fam not in TARGET_FAMILIES:
            continue
        by_fam[fam].append(s)
    if not by_fam:
        raise SystemExit("❌ 一条候选都没选出来 —— 先验扫描本身，别信这个 0")
    for fam in by_fam:
        by_fam[fam].sort(key=lambda s: len(s["turns"][-1]["content"]))
    picked, fams = [], sorted(by_fam)
    i = 0
    while len(picked) < n:
        added = False
        for fam in fams:
            if i < len(by_fam[fam]) and len(picked) < n:
                picked.append(by_fam[fam][i])
                added = True
        if not added:
            break
        i += 1
    return picked


def build(sample: dict) -> dict:
    turns = sample["turns"]
    user = " / ".join(t["content"] for t in turns if t.get("role") == "user")
    calls, obs_texts = [], []
    for t in turns:
        if t.get("role") == "tool_call":
            calls += [f'{c["name"]}({json.dumps(c.get("arguments", {}), ensure_ascii=False)})'
                      for c in t.get("calls", [])]
        elif t.get("role") == "tool_result":
            obs_texts += [json.dumps(r.get("content"), ensure_ascii=False)
                          for r in t.get("results", [])]
    ref = turns[-1]["content"]
    prompt = REWRITE_TMPL.format(user=user, call=" ; ".join(calls),
                                 observation="\n".join(obs_texts), ref=ref)
    return {
        "id": sample["id"], "template_id": sample["template_id"],
        "family": sample["template_id"].split("__")[0],
        "ref": ref, "ref_len": len(ref),
        # 忠实度判据的上下文：与 eval.py 同口径 —— system + 给定轮次的全部文本。
        "context": sample["system"] + " " + user + " " + " ".join(obs_texts),
        "observations": obs_texts,
        "messages": [{"role": "system", "content": sample["system"]},
                     {"role": "user", "content": prompt}],
    }


def gate(item: dict, text: str) -> dict:
    """三道闸门。⚠️ 字数**不是**闸门，只是观测量。"""
    ents = observation_entities(item["observations"])
    bad = unsupported_numbers(text, item["context"], ents) if ents else set()
    return {
        "忠实度": ("跳过（观测抽不出实体，如实报无法比对）" if not ents
                else ("✅" if not bad else f"❌ 编了 {sorted(bad)}")),
        "非空": "✅" if text.strip() else "❌ 空",
        "没跑题": "✅" if len(text) < 4000 else "❌ 超长疑似跑飞",
        "字数": len(text),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true", help="只选样本+拼提示词，不连模型")
    ap.add_argument("--endpoint")
    ap.add_argument("--model", default="esa-base")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--resume", action="store_true",
                    help="接着 --out 里已有的那些往下跑（作业 87509 挂在第 4 条，"
                         "而产物在循环之后才写，3 条全丢）")
    ap.add_argument("--timeout", type=int, default=600,
                    help="单次请求读超时（秒）。87509 就是在这上面挂的 —— "
                         "但根因是 base 在改写任务上思考 8725 字，"
                         "正解是起服务时 enable_thinking: false，不是把这个数字调大")
    ap.add_argument("--show", type=int, default=5, help="打印几条原文供人过眼")
    args = ap.parse_args()

    items = [build(s) for s in candidates(args.n)]
    fam_n = defaultdict(int)
    for it in items:
        fam_n[it["family"]] += 1
    print(f"选出 {len(items)} 条（按族轮转，每族取最短的）：")
    for fam, k in sorted(fam_n.items()):
        print(f"  {fam:<28}{k:>3} 条   该族末轮中位 {TARGET_FAMILIES[fam]} 字")
    print(f"\n参考回答字数：中位 {sorted(i['ref_len'] for i in items)[len(items)//2]}，"
          f"最长 {max(i['ref_len'] for i in items)}")
    print(f"排除的族（本来就该短，5.68）：{'、'.join(CORRECTLY_SHORT)}")

    if args.dry_run:
        print("\n" + "=" * 70 + "\n第一条的完整提示词（人先看一眼再上机）：\n")
        print(items[0]["messages"][1]["content"][:1600])
        return 0

    if not args.endpoint:
        ap.error("要么 --dry-run，要么给 --endpoint")

    # 🔴 逐条落盘，别等循环跑完再写。作业 87509 就是这么亏掉的：第 4 条抛异常，
    #    前 3 条已经花了机时算出来，却因为 `write_text` 在循环之后而**一个字节都没留**。
    #    `eval.py` 的 `predict` 早在〇之三 就为同一个理由加了 `--resume`，
    #    这个脚本没继承过来 —— 5.54 同形：同一个概念两处各写一遍，就是在等它们分叉。
    done: dict[str, dict] = {}
    if args.out and args.resume and args.out.exists():
        done = {r["id"]: r for r in (json.loads(x) for x in
                                     args.out.open(encoding="utf-8") if x.strip())}
        print(f"\n续跑：{args.out} 里已有 {len(done)} 条，跳过它们")
    fh = None
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        fh = args.out.open("a" if done else "w", encoding="utf-8")

    results, failed = list(done.values()), []
    parse = PARSERS["current"]
    for k, it in enumerate(items, 1):
        if it["id"] in done:
            continue
        try:
            raw = call_endpoint(args.endpoint, args.model, it["messages"], [],
                                timeout=args.timeout)
        except Exception as exc:  # noqa: BLE001
            # 单条失败不拖垮整轮，但**必须响**：进 failed、末尾单独报、退出码非 0。
            # 5.33：别把「不知道」和「没事」压成同一个灯 —— 静默 continue 会让
            # 一份只有 11 条的产物长得和跑满 30 条的一模一样。
            failed.append((it["id"], f"{type(exc).__name__}: {exc}"))
            print(f"  [{k:>2}/{len(items)}] {it['family']:<26} 🔴 调用失败  "
                  f"{type(exc).__name__}: {str(exc)[:160]}", flush=True)
            continue
        # 🔴 base 的 think 中位 291 字。必须用**判分器同一个解析器**把正文剥出来：
        #    ① 不剥的话「字数」量的是思考+正文，数字全是假的；
        #    ② 更要命的是带 `<think>` 的文本会被存进 pilot.jsonl，
        #       那种东西一旦进训练数据，就是把机制一原样种回去。
        pr = parse(raw)
        text = pr.content
        g = gate(it, text)
        rec = {**{x: it[x] for x in ("id", "template_id", "family", "ref", "ref_len")},
               "rewritten": text, "think_len": len(pr.reasoning),
               "raw_len": len(raw), "had_tool_call": bool(pr.tool_calls), "gate": g}
        results.append(rec)
        if fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
        flag = "  ⚠️改写里冒出了工具调用" if pr.tool_calls else ""
        # think 比正文还长得多 = 大概率被 max_tokens 8192 截在思考里，正文是残的。
        if len(pr.reasoning) > 3000 and len(text) < len(pr.reasoning) / 10:
            flag += "  ⚠️think 吃满、正文疑似被截"
        print(f"  [{k:>2}/{len(items)}] {it['family']:<26} "
              f"{it['ref_len']:>4} → {g['字数']:>4} 字"
              f"（think {len(pr.reasoning):>4}）  {g['忠实度']}{flag}", flush=True)
    if fh:
        fh.close()
        print(f"\n→ {args.out}（{len(results)} 条）")

    if not results:
        print("\n🔴 一条都没跑成 —— 下面的统计全部略过，别拿空表当『通过』")
        for qid, msg in failed[:10]:
            print(f"     {qid}  {msg}")
        return 1

    ok = sum(1 for r in results if r["gate"]["忠实度"].startswith("✅"))
    skip = sum(1 for r in results if r["gate"]["忠实度"].startswith("跳过"))
    lens = sorted(r["gate"]["字数"] for r in results)
    print("\n══ 闸门 ══")
    print(f"  忠实度  ✅ {ok}   ❌ {len(results)-ok-skip}   跳过 {skip}")
    print(f"  字数    参考中位 {sorted(r['ref_len'] for r in results)[len(results)//2]}"
          f" → 改写后中位 {lens[len(lens)//2]}（**观测量，不是判据**）")
    calls = sum(1 for r in results if r["had_tool_call"])
    print(f"  纯净度  改写里冒出工具调用的：{calls} 条"
          f"（必须是 0 —— 改写只该产出散文，工具调用是固定住的）")
    tl = sorted(r["think_len"] for r in results)
    print(f"  think   中位 {tl[len(tl)//2]} 字（已剥离，不进训练目标）")
    print(f"\n══ 供人过眼的 {args.show} 条（判的是结构，不是长度）══")
    for r in results[:args.show]:
        print(f"\n── {r['template_id']} ──")
        print(f"  原：{r['ref']}")
        print(f"  新：{r['rewritten'][:700]}")
        print(f"  闸门：{r['gate']}")
    print("\n⚠️ 三条有一条不过，这条路要改法，不是加量：")
    print("   ① 忠实度还过不过（会不会编数字）")
    print("   ② 结构是不是「机制 → 依据 → 下一步」，而不是把同一句话说三遍")
    print("   ③ 有没有引入参考回答里没有的结论/承诺（语义等价）")

    if failed:
        # 退出码 2 = 「有产物但不完整」，沿用本项目 0/1/2 的约定（5.33）。
        # ⚠️ 上面那几个中位数是**在跑成的那些上**算的，别拿它们当 30 条的结论。
        print(f"\n🔴 {len(failed)} 条调用失败，上面的统计只覆盖跑成的 {len(results)} 条。"
              f"\n   加 --resume 接着跑（已跑的不会重算）：")
        for qid, msg in failed[:10]:
            print(f"     {qid}  {msg}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
