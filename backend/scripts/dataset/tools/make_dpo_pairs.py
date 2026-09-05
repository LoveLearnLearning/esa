"""从评测的**真实失败**里挑偏好对，供 DPO / SimPO 使用。

    # 只看复核表，不落盘
    python3 dataset/tools/make_dpo_pairs.py \
        --eval data/eval/eval.jsonl \
        --pred $HOME/esa_results/pred_lora_80269.jsonl \
        --report $HOME/esa_results/report_lora_80269.json

    # 复核过了再落盘
    ... --out data/out/dpo_pairs.jsonl

为什么是「从失败里挑」而不是造新数据
------------------------------------
5.44 的结论：补数据对**结构/语序**类缺口有效，对**需要反直觉语义判断**的缺口无效
（`个人数据_03` 加了 4 条同形样本纹丝不动）。原因是 SFT 只能说「照这个答」，
说不了「**别照那个答**」。DPO 教的正是后者，而它要的两半我们都已经有了：

    chosen   = 评测集里的参考答案（`conversations` 里给定轮次之后那一轮）
    rejected = 模型**实际**给出的错误答案（`pred_*.jsonl` 的 raw）

所以这批偏好对**没有一条是编的**，全部来自真实失败。

🔴 三道闸门（都在下面实现，别拆）
--------------------------------
1. **考卷指纹必须对上**。`pred_*.jsonl` 首行 `_meta.eval_fingerprint` 与 `--eval`
   那份文件现算的指纹逐字比（算法抄 `esa.eval.eval_fingerprint`：sha256 前 16 位 +
   `#题数`）。对不上就是拿一个模型的输出去配另一套题 —— 而这**不会有任何东西报错**，
   只会得到一批看着正常、其实错位的偏好对。
2. **rejected 必须真的存在且非空**。空预测是请求失败的产物，
   拿空串当「坏答案」等于教模型「什么都不说是对的」。
3. **chosen 必须真的是一段答案**。给定轮次之后没有参考回答的题跳过。

⚠️ 本脚本**只负责挑**，不负责判断这一对该不该用。`gold` 本身可能有问题
（〇之四作废的 `能力边界_01` 就是我们自己的标注矛盾），而 DPO 优化的是
「相对偏好」不是「正确答案」——把矛盾当目标学进去是会的。
**每一对都要人工过一眼**，量很小，看得过来。所以 `--out` 不给就只印复核表、不落盘。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# 与 esa/eval.py 一致：这两项 `_items` 里记的 1 是**失败**，其余项 1 是成功。
#
# 📌 2026-08-26：集群上那份是本文件的**文档字符串精简版**（粘贴时压缩过）。
# 功能代码逐节点相同 —— 核对方法见下，但**必须用同一个 Python 版本跑**：
#   剥掉文档字符串后 `len(ast.dump(tree))`，
#   Python 3.9 上是 24727、3.13 上是 22757。**跨版本比这个数没有意义**
#   （同一个文件 3.9 给 24728、3.13 给 22758，差 2000 —— 那是 AST 节点字段变了）。
LOWER_IS_BETTER = ("误触发率 FPR", "漏调率 FNR")


def eval_fingerprint(path: Path) -> str:
    """抄 `esa.eval.eval_fingerprint`：sha256 前 16 位 + `#非空行数`。"""
    raw = path.read_bytes()
    n = sum(1 for line in raw.splitlines() if line.strip())
    return f"{hashlib.sha256(raw).hexdigest()[:16]}#{n}"


def load_preds(path: Path) -> tuple[dict[str, str], str | None]:
    preds: dict[str, str] = {}
    meta_fp: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "id" not in row:
            meta_fp = row.get("_meta", {}).get("eval_fingerprint")
            continue
        preds[row["id"]] = row.get("raw", "")
    return preds, meta_fp


def gold_reply(rec: dict) -> str:
    """给定轮次之后的第一条助手回答 —— 也就是这道题的参考答案。

    `n_turns_given` 说的是喂给模型几轮，其后那一条 `gpt` 就是参考。
    """
    convs = rec.get("conversations", [])
    given = rec["gold"].get("n_turns_given", 1)
    seen_human = 0
    for turn in convs:
        if turn.get("from") in ("human", "user"):
            seen_human += 1
            continue
        if turn.get("from") in ("gpt", "assistant") and seen_human >= given:
            return turn.get("value", "")
    return ""


def called_tool(raw: str) -> str:
    """从模型原始输出里粗取它调了哪个工具，只用于复核表显示。"""
    if '"name":' not in raw:
        return "—"
    return raw.split('"name":', 1)[1].split(",", 1)[0].strip(' "\n\t{}')


def main() -> int:
    ap = argparse.ArgumentParser(description="从评测失败里挑 DPO 偏好对")
    ap.add_argument("--eval", required=True)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--metric", default="误触发率 FPR",
                    help="按哪一项的失败挑；逗号分隔可给多项")
    ap.add_argument("--out", help="不给就只印复核表、不落盘")
    ap.add_argument("--max-chars", type=int, default=400, help="复核表里正文截断长度")
    args = ap.parse_args()

    eval_path, pred_path, report_path = Path(args.eval), Path(args.pred), Path(args.report)
    recs = {}
    for line in eval_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            recs[r["gold"]["id"]] = r

    preds, meta_fp = load_preds(pred_path)
    want_fp = eval_fingerprint(eval_path)

    # ── 闸门 1：考卷指纹 ──────────────────────────────────────────────
    if meta_fp != want_fp:
        sys.exit(
            "❌ 闸门1：这份预测不是对着这套评测集跑出来的，拒绝配对。\n"
            f"   预测里记的：{meta_fp or '（没有 —— 旧版 predict 的产物）'}\n"
            f"   评测集现算：{want_fp}\n"
            "   —— 拿一个模型的输出去配另一套题，得到的偏好对会看着完全正常。"
        )
    print(f"✅ 闸门1：考卷指纹一致 {want_fp}")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    items = report.get("_items", {})

    metrics = [m.strip() for m in args.metric.split(",") if m.strip()]
    unknown = [m for m in metrics if m not in items]
    if unknown:
        sys.exit(f"❌ 报告里没有这些项：{unknown}\n   可选：{sorted(items)}")

    pairs, skipped = [], []
    for metric in metrics:
        fail_value = 1 if metric in LOWER_IS_BETTER else 0
        rids = [rid for rid, v in items[metric].items() if v == fail_value]
        print(f"\n═══ {metric}：{len(rids)} 条失败 ═══")
        for rid in rids:
            rec = recs.get(rid)
            if rec is None:
                skipped.append((rid, metric, "评测集里找不到这个 id"))
                continue
            rejected = preds.get(rid, "")
            chosen = gold_reply(rec)
            if not rejected.strip():                       # 闸门 2
                skipped.append((rid, metric, "模型没有输出（空预测）"))
                continue
            if not chosen.strip():                         # 闸门 3
                skipped.append((rid, metric, "评测集里没有参考答案"))
                continue
            user = ""
            for turn in rec["conversations"]:
                if turn.get("from") in ("human", "user"):
                    user = turn.get("value", "")
            pairs.append({
                "_id": rid,
                "_metric": metric,
                "_template_id": rec["gold"].get("template_id", ""),
                "_expected_action": rec["gold"].get("expected_action", ""),
                "_wrong_tool": called_tool(rejected),
                "system": rec.get("system", ""),
                "tools": rec.get("tools", ""),
                "conversations": [t for t in rec["conversations"]
                                  if t.get("from") in ("human", "user")][:1],
                "chosen": chosen,
                "rejected": rejected,
                "_user": user,
            })

    # ── 复核表：人要看的就是这张 ──────────────────────────────────────
    n = args.max_chars
    for p in pairs:
        print(f"\n── {p['_id']}　[{p['_template_id']}]　gold={p['_expected_action']}")
        print(f"   用户：{p['_user'][:120]}")
        print(f"   ❌ 模型（错调 {p['_wrong_tool']}）：{p['rejected'][:n].strip()}")
        print(f"   ✅ 参考：{p['chosen'][:n].strip()}")

    if skipped:
        print(f"\n⚠️ 跳过 {len(skipped)} 条：")
        for rid, metric, why in skipped:
            print(f"   {rid}　[{metric}]　{why}")

    print(f"\n合计可用偏好对：{len(pairs)} 对")
    print("⚠️ 落盘之前逐条看一遍 —— gold 本身出问题时，DPO 会把矛盾当目标学进去。")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for p in pairs:
                fh.write(json.dumps(p, ensure_ascii=False) + "\n")
        print(f"→ 已写入 {out}（{len(pairs)} 对）")
    else:
        print("（没给 --out，未落盘。复核过了再加上它。）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
