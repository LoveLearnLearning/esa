"""查「这份考卷里有多少题，是这个模型训练时见过的」。

    python3 dataset/tools/check_eval_leak.py --eval data/eval/eval.jsonl \\
        --train-ir /persist_data/home/chenxuzhao/esa_results/era_80269/train_ir.jsonl

为什么需要这道闸门
------------------
2026-08-27 差点把一张泄题的表交出去：定版模型 **80269** 训在上一版数据上，
而新考卷 `330277da20d87755#456` 是**新数据**跑 `esa.evalset` 生成的。
逐条一比：**86 个模板里 29 个在它的训练集里，涉及 110 道题 = 考卷的 24.1%。**

`esa/split.py` 的 `assert_no_leak` 只保证「**这一版数据自己的**切分」不泄漏。
**它不知道世上还存在一个用别版数据训出来的模型**，所以七道闸门一个都没响。

📌 **定式：任何「旧模型 × 新考卷」的组合，跑之前先算一次模板交集。**

失效方向（5.41）
----------------
- 找不到 `train_ir` → **退出码 2「判不了」**，警告但不拦。
  评测本身仍然有效，杀掉一个 6 小时的作业代价太大。
- 有交集 → **退出码 1**，把题号清单写出来给下游用。
  真正 fail-closed 的地方在 `export_figure_data.py`：**没摘就不许出图表数据**。
  在「产生危害的那一步」拦，而不是在「产生数据的那一步」拦。

⚠️ 反直觉的一条实测：**泄露不一定抬高分数。** 那 110 道里
`get_weak_prerequisites__正例` 48 道是两个模型都栽的题，摘掉之后 80269 的
工具选择反而 87.4% → 88.4%。**但这不改变结论：一张 24% 的题目出现在
模型训练集里的对比表，跟它有没有把数字抬高无关，就是不能交付。**
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def exam_templates(eval_path: Path) -> dict[str, str]:
    """考卷的 题号 → template_id。"""
    out = {}
    for rec in load_jsonl(eval_path):
        gold = rec.get("gold", {})
        if gold.get("id"):
            out[gold["id"]] = gold.get("template_id")
    return out


def train_templates(train_ir: Path) -> set[str]:
    return {r["template_id"] for r in load_jsonl(train_ir) if r.get("template_id")}


def analyse(eval_path: Path, train_ir: Path) -> dict:
    id2tpl = exam_templates(eval_path)
    if not id2tpl:
        raise SystemExit(f"❌ {eval_path} 里一个带 gold.id 的样本都没读到 —— "
                         "别信这次的『零交集』（5.22：扫出 0 先验扫描本身）")
    trained = train_templates(train_ir)
    if not trained:
        raise SystemExit(f"❌ {train_ir} 里一个 template_id 都没读到，同上")
    hit_tpl = sorted({t for t in id2tpl.values() if t in trained})
    hit_ids = sorted(i for i, t in id2tpl.items() if t in trained)
    return {
        "eval": str(eval_path), "train_ir": str(train_ir),
        "n_exam": len(id2tpl), "n_exam_templates": len(set(id2tpl.values())),
        "n_train_templates": len(trained),
        "leaked_templates": hit_tpl, "leaked_ids": hit_ids,
        "leak_ratio": len(hit_ids) / len(id2tpl),
    }


def self_test() -> int:
    """三条：抓得住重叠、不误报、读不到就喊「判不了」。"""
    import tempfile
    ok = 0
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        ev = d / "eval.jsonl"
        ev.write_text("\n".join(json.dumps(
            {"gold": {"id": f"q{i}", "template_id": f"t{i}"}}, ensure_ascii=False)
            for i in range(5)) + "\n", encoding="utf-8")

        tr = d / "train_overlap.jsonl"
        tr.write_text("\n".join(json.dumps({"template_id": f"t{i}"}) for i in (1, 3))
                      + "\n", encoding="utf-8")
        r = analyse(ev, tr)
        assert r["leaked_ids"] == ["q1", "q3"], r
        assert abs(r["leak_ratio"] - 0.4) < 1e-9, r
        print("✅ 有重叠时抓得住（2/5）")
        ok += 1

        tr2 = d / "train_clean.jsonl"
        tr2.write_text(json.dumps({"template_id": "zzz"}) + "\n", encoding="utf-8")
        assert analyse(ev, tr2)["leaked_ids"] == []
        print("✅ 无重叠时不误报")
        ok += 1

        # 空文件必须喊出来，不能安静地报「零交集」
        empty = d / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        try:
            analyse(ev, empty)
        except SystemExit:
            print("✅ 训练数据读不到时拒绝下结论（5.22）")
            ok += 1
        else:
            print("❌ 空训练数据竟然报了『零交集』")
            return 1
    print(f"\n{ok}/3 通过")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval", type=Path, default=Path("data/eval/eval.jsonl"))
    ap.add_argument("--train-ir", type=Path,
                    help="该模型那一版的 train_ir.jsonl（通常在 esa_results/era_<tag>/）")
    ap.add_argument("--tag", help="只用于提示文案")
    ap.add_argument("--out", type=Path, help="把泄露清单写成 JSON 给下游用")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.train_ir:
        ap.error("要么 --self-test，要么给 --train-ir")

    who = f"（tag={args.tag}）" if args.tag else ""
    if not args.train_ir.exists():
        print(f"⚠️ 判不了{who}：{args.train_ir} 不在。\n"
              "   评测产物本身仍然有效，但**不要拿它和别的模型做对比表**，\n"
              "   除非先把那一版的 train_ir 找出来算一次交集。", file=sys.stderr)
        return 2
    if not args.eval.exists():
        print(f"⚠️ 判不了：{args.eval} 不在。", file=sys.stderr)
        return 2

    r = analyse(args.eval, args.train_ir)
    if args.out:
        args.out.write_text(json.dumps(r, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")

    n, total = len(r["leaked_ids"]), r["n_exam"]
    if not n:
        print(f"✅ 零泄露{who}：考卷 {total} 道 / {r['n_exam_templates']} 模板，"
              f"与训练模板（{r['n_train_templates']} 个）交集为 0")
        return 0

    print(f"🔴 泄题{who}：考卷 {total} 道里有 **{n} 道**（{r['leak_ratio']:.1%}）"
          f"的模板出现在训练集中，共 {len(r['leaked_templates'])} 个模板：")
    for t in r["leaked_templates"]:
        print(f"     {t}")
    print("\n   评测产物本身仍然有效 —— 但**这个模型的成绩不能直接进对比表**。")
    print("   出图表数据时用 tools/export_figure_data.py --exclude-train-ir <这份 train_ir>，")
    print("   并在报告里写明：摘了哪些、为什么、两个模型摘的是同一批、"
          "以及摘除发生在看到结果之后。")
    if args.out:
        print(f"   清单已写入 {args.out}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
