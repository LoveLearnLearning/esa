#!/usr/bin/env python3
"""量「模型话多话少」。

后端队友反馈初版模型输出特别简短。这个脚本不看报表，直接量预测文件：
每题的 `<think>` 有多长、正文有多长，按类别分组，并把 base 与微调后并排比。

判据不是「字数越多越好」——拒绝和追问本来就该短。要看的是**同一类题上
微调前后的落差**：如果 DIRECT_ANSWER 类正文从基座的 300 字掉到 60 字，
那就是我们训短的，不是模型本来就短。

用法（🖥️ 集群上，**在 `.../backend/scripts/dataset` 目录里跑**，与
`cluster_manifest.py` 一样的调法）：

    python tools/measure_verbosity.py \\
        --eval data/eval/eval.jsonl \\
        --pred base=/persist_data/home/chenxuzhao/esa_results/pred_base.jsonl \\
        --pred 80269=/persist_data/home/chenxuzhao/esa_results/pred_lora_80269.jsonl

`--pred` 可给任意多个，标签随意。只给一个也能跑（就只看分布，不做对比）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa.backend_parser import PARSERS  # noqa: E402
from esa.preds import fingerprint_of, load_preds_file  # noqa: E402

# ⚠️ 预测文件的读取和指纹计算都用 esa.preds 里的那一份，别在这里再写一遍。
# 🔴 从 esa.preds 而不是 esa.eval import —— 后者顶上有 jsonschema/transformers，
#    2026-08-26 在集群上就是这么炸的（ModuleNotFoundError: jsonschema）。
# 2026-08-26 这个脚本第一版自己写了 `load_pred`，直接 `r["id"]` ——
# 而预测文件**首行是 `_meta` 指纹行、没有 `id`**，当场 KeyError。
# eval.py 里 predict 那段的注释早就写了「`load_preds` 会跳过没有 id 的行」。
# 同一个概念两处各写一遍，就是在等它们分叉（5.54）。


def load_gold(path: Path) -> dict[str, dict]:
    """eval.jsonl → {id: gold}。"""
    gold = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            g = json.loads(line)["gold"]
            gold[g["id"]] = g
    return gold


def quantiles(vals: list[int]) -> dict[str, int]:
    if not vals:
        return {}
    s = sorted(vals)
    n = len(s)
    pick = lambda p: s[min(n - 1, int(p * n))]  # noqa: E731
    return {"n": n, "p10": pick(0.10), "med": pick(0.50),
            "p90": pick(0.90), "max": s[-1]}


def measure(gold: dict, raws: dict[str, str], parser_name: str) -> dict:
    """按 expected_action 分组，量 reasoning / content 的长度。"""
    parse = PARSERS[parser_name]
    buckets: dict[str, dict[str, list]] = defaultdict(
        lambda: {"think": [], "body": [], "body_spoken": [], "empty_think": 0, "has_call": 0})
    missing = 0
    for qid, g in gold.items():
        raw = raws.get(qid)
        if raw is None:
            missing += 1
            continue
        p = parse(raw)
        b = buckets[g.get("expected_action", "?")]
        b["think"].append(len(p.reasoning))
        b["body"].append(len(p.content))
        if not p.reasoning.strip():
            b["empty_think"] += 1
        if p.tool_calls:
            b["has_call"] += 1
        else:
            # 🔴 2026-08-27：正文长度的分母里不能混「根本没开口」的题。
            # 85362 探针上 DIRECT_ANSWER 76 题里有 21 题只吐了 tool_call、
            # 正文为空（那是误触发，另一条线的事），于是「正文中位 25 字」
            # 是被 21 个 0 拽下来的。5.26 / 5.28 同形：分母固定还不够，
            # 分母里装的必须是同一种东西。
            b["body_spoken"].append(len(p.content))
    return {"buckets": dict(buckets), "missing": missing}


def render(tag: str, res: dict) -> None:
    print(f"\n=== {tag} ===")
    if res["missing"]:
        print(f"  ⚠️ 有 {res['missing']} 道题在这份预测里没有（考卷与预测不配套？）")
    head = (f"{'类别':<16}{'n':>5}{'think空':>8}{'调了工具':>9}"
            f"{'正文中位':>9}{'开口中位':>9}{'开口p90':>9}{'think中位':>10}")
    print(head)
    for act, b in sorted(res["buckets"].items(), key=lambda x: -len(x[1]["body"])):
        q = quantiles(b["body"])
        qs = quantiles(b["body_spoken"])
        qt = quantiles(b["think"])
        n = q["n"]
        empty = b["empty_think"] / n * 100
        # 一整类都在调工具时 body_spoken 是空的 —— 印「—」，别拿 0 冒充。
        s_med = f"{qs['med']}" if qs else "—"
        s_p90 = f"{qs['p90']}" if qs else "—"
        print(f"{act:<16}{n:>5}{empty:>7.0f}%{b['has_call']:>6}/{n:<2}"
              f"{q['med']:>9}{s_med:>9}{s_p90:>9}{qt['med']:>10}")
    print("  「正文中位」的分母含调了工具、正文为空的题；"
          "「开口中位」只算没调工具、真开口说话的那些 —— 两者差得越大，"
          "说明这一类里越多题是被误触发吃掉的，不是回答变短了。")


def compare(tags: list[str], results: list[dict]) -> None:
    """两份以上时，逐类别打并排差值。"""
    if len(tags) < 2:
        return
    base_tag = tags[0]
    acts = sorted({a for r in results for a in r["buckets"]})
    print(f"\n=== 与 {base_tag} 的落差（开口中位字数：只算没调工具、真说了话的题） ===")
    header = f"{'类别':<16}" + "".join(f"{t:>12}" for t in tags)
    print(header)
    for act in acts:
        cells = []
        base_med = None
        for i, r in enumerate(results):
            b = r["buckets"].get(act)
            if not b:
                cells.append("—")
                continue
            spoken = quantiles(b["body_spoken"])
            if not spoken:
                cells.append("—")   # 这一类全在调工具，没有「开口」的样本
                continue
            med = spoken["med"]
            if i == 0:
                base_med = med
                cells.append(str(med))
            else:
                delta = med - base_med if base_med is not None else 0
                cells.append(f"{med} ({delta:+d})")
        print(f"{act:<16}" + "".join(f"{c:>12}" for c in cells))

    print(f"\n=== 与 {base_tag} 的落差（think 空的比例） ===")
    print(header)
    for act in acts:
        cells = []
        for r in results:
            b = r["buckets"].get(act)
            if not b:
                cells.append("—")
                continue
            n = len(b["body"])
            cells.append(f"{b['empty_think'] / n * 100:.0f}%")
        print(f"{act:<16}" + "".join(f"{c:>12}" for c in cells))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval", required=True, type=Path, help="eval.jsonl / eval_supp.jsonl")
    ap.add_argument("--pred", action="append", required=True, metavar="标签=路径",
                    help="可重复；第一个当作对比基准")
    ap.add_argument("--parser", default="current", choices=list(PARSERS))
    args = ap.parse_args()

    gold = load_gold(args.eval)
    eval_fp = fingerprint_of(args.eval)
    print(f"考卷 {args.eval}：{len(gold)} 道题  指纹 {eval_fp}")

    tags, results, mismatched = [], [], []
    for spec in args.pred:
        if "=" not in spec:
            ap.error(f"--pred 要写成 标签=路径，收到 {spec!r}")
        tag, path = spec.split("=", 1)
        p = Path(path)
        if not p.exists():
            ap.error(f"预测文件不存在：{p}")
        meta, raws = load_preds_file(p)
        pred_fp = meta.get("eval_fingerprint")
        if pred_fp and pred_fp != eval_fp:
            mismatched.append((tag, pred_fp))
        res = measure(gold, raws, args.parser)
        tags.append(tag)
        results.append(res)
        fp_note = f"  指纹 {pred_fp}" if pred_fp else "  ⚠️ 这份预测没有指纹行"
        render(f"{tag}  ({p.name}, {len(raws)} 条预测){fp_note}", res)

    if mismatched:
        print("\n🔴 考卷与预测不配套 —— 下面的数字不作数（5.59）：")
        for tag, fp in mismatched:
            print(f"    {tag}: 预测是对着 {fp} 跑的，而当前考卷是 {eval_fp}")
        print("    改用与模型同期的那份考卷，例如 esa_results/era_80269/eval.jsonl")

    compare(tags, results)
    print("\n注：拒绝(REFUSE)、追问(ASK_USER)本来就该短，看它们的绝对值没意义；")
    print("    要看的是 DIRECT_ANSWER / RESPOND 这类「该展开说」的题上，微调后掉了多少。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
