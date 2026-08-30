"""🖥️ **集群上跑。** 把两份报告压成一小段 JSON，印出来粘回本机画图。

    cd /persist_data/home/chenxuzhao/esa-data/backend/scripts/dataset
    PYTHONPATH=. python tools/export_figure_data.py \\
        --base base --lora 80269 \\
        --exclude-train-ir /persist_data/home/chenxuzhao/esa_results/era_80269/train_ir.jsonl

为什么要有这一步
----------------
本机连不上超算（手册 3350：`scp` 不通，同步只能靠粘贴），147 KB 的 report
粘不回来。所以在集群上把「画图需要的那点数」算好，印成几 KB 的 JSON。

`--exclude-train-ir` 是这次真正踩到的坑
----------------------------------------
2026-08-27：80269 训在上一版数据上，而新考卷 86 个模板里有 **29 个
（110 道题 / 24.1%）在它的训练集里** —— 拿那张表交付就是拿泄题的成绩交付。
`split.assert_no_leak` 只保证「这一版数据自己的切分」不泄漏，
**它不知道世上还有个用别版数据训出来的模型，也没有任何闸门会报。**

📌 **定式：任何「旧模型 × 新考卷」的组合，先算一次模板交集。**
摘除对两个模型同时生效，并且**必须写进报告**：摘了哪些、为什么、
以及摘除发生在看到结果之后。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa.figure_data import build  # noqa: E402


def template_ids(path: Path) -> set[str]:
    out = set()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.add(json.loads(line)["template_id"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval", type=Path, default=Path("data/eval/eval.jsonl"))
    ap.add_argument("--reports", type=Path, default=Path("data/eval"))
    ap.add_argument("--base", default="base")
    ap.add_argument("--lora", required=True)
    ap.add_argument("--exclude-train-ir", type=Path, default=None,
                    help="把模板出现在这份训练数据里的题摘掉（旧模型 × 新考卷必做）")
    ap.add_argument("--assert-clean", type=Path, default=None,
                    help="断言这份 train_ir 与考卷零交集；有交集就拒绝出数据")
    ap.add_argument("--no-leak-check", action="store_true",
                    help="明知有泄题也照出（只在你打算另行说明时用）")
    ap.add_argument("--out", type=Path, default=None,
                    help="同时写一份文件；默认只印到 stdout（粘贴用）")
    args = ap.parse_args()

    # 🔴 fail-closed：泄题这件事必须**显式表态**，不许沉默地出一张对比数据。
    # 闸门放在这一步而不是评测那一步 —— 评测产物本身没错，
    # 错的是拿它做的比较（5.41：闸门的失效方向要选对）。
    chosen = [bool(args.exclude_train_ir), bool(args.assert_clean), args.no_leak_check]
    if sum(chosen) != 1:
        raise SystemExit(
            "❌ 必须且只能选一个：\n"
            "   --exclude-train-ir <train_ir>  摘掉该模型训练时见过的题（旧模型 × 新考卷）\n"
            "   --assert-clean     <train_ir>  断言零交集，有交集就拒绝出\n"
            "   --no-leak-check                明知有泄题也照出（要另行说明）\n"
            "   ⚠️ 2026-08-27：新考卷 86 个模板里有 29 个在定版模型 80269 的训练集中，"
            "涉及 110 道 = 24.1%。split.assert_no_leak 管不了「用别版数据训出来的模型」。")

    recs = [json.loads(line) for line in args.eval.open(encoding="utf-8") if line.strip()]
    layer_of = {r["gold"]["id"]: r["gold"].get("layer") for r in recs
                if r["gold"].get("layer")}
    action_of = {r["gold"]["id"]: r["gold"].get("expected_action") for r in recs
                 if r["gold"].get("expected_action")}

    drop, reason = frozenset(), ""
    if args.assert_clean:
        hit = {t for t in
               {json.loads(x)["gold"].get("template_id") for x in
                args.eval.open(encoding="utf-8") if x.strip()}
               if t in template_ids(args.assert_clean)}
        if hit:
            raise SystemExit(
                f"❌ --assert-clean 不成立：{len(hit)} 个模板同时出现在考卷和 "
                f"{args.assert_clean.name} 里。\n   " + "\n   ".join(sorted(hit)) +
                "\n   改用 --exclude-train-ir 摘掉它们，或明确 --no-leak-check。")
        print(f"✅ --assert-clean 通过：与 {args.assert_clean.name} 零交集",
              file=sys.stderr)
    if args.no_leak_check:
        reason = "⚠️ 未做泄题检查（--no-leak-check）"
        print(reason, file=sys.stderr)
    if args.exclude_train_ir:
        leak = template_ids(args.exclude_train_ir)
        id2tpl = {r["gold"]["id"]: r["gold"].get("template_id") for r in recs}
        hit = sorted({t for t in id2tpl.values() if t in leak})
        drop = frozenset(i for i, t in id2tpl.items() if t in leak)
        reason = (f"摘除 {len(drop)} 道：其 template_id（{len(hit)} 个）出现在 "
                  f"{args.exclude_train_ir.name} 中；两个模型摘同一批")
        # 印在 stderr，好让人一眼看见摘了什么 —— 摘除不能是静默的。
        print(f"⚠️ {reason}", file=sys.stderr)
        for t in hit:
            print(f"     {t}", file=sys.stderr)

    def load(tag: str) -> dict:
        f = args.reports / f"report_{tag}.json"
        if not f.exists():
            raise SystemExit(f"❌ 报告不在：{f}（先跑 esa.eval score --tag {tag}）")
        return json.loads(f.read_text(encoding="utf-8"))

    data = build(load(args.base), load(args.lora), args.base, args.lora,
                 layer_of=layer_of, action_of=action_of,
                 drop=drop, drop_reason=reason)
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"→ {args.out}", file=sys.stderr)
    print(f"\n===== 复制下面整段（{len(text)} 字节）到本机 "
          f"dataset/data/eval/figure_data.json =====\n", file=sys.stderr)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
