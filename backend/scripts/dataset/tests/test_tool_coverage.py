#!/usr/bin/env python3
"""闸门：考卷考的工具、训练池训的工具，两边的分配必须是**有意的**。

为什么要有这道
--------------
2026-09-03 复盘时发现 `get_review_timing` 在考卷上有 49 道题（`CALL_TOOL`
类里最多的一个工具），训练池里**一条正例都没有**。第一反应是「切分漏了」——
查完源码才知道**这是设计**：`evalset.L3_HOLDOUT_PREFIXES` 把它整族留出来当
L3「未见工具」那一层，而 L3 上 base 3.9% → lora 80.4% 是整份报告里最强的
一条泛化证据。**差点照着「补训练样本」去改，那会把 L3 这一层直接删掉。**

于是这道闸门守的是两个方向，两个都是硬判据：

  ① 考卷有、训练零 —— 除非它被 `L3_HOLDOUT_PREFIXES` 明确留出。
     没有这条，下一个「模板少的工具整族落到考卷侧」不会有任何人发现。
  ② 被留出的工具，训练池里**必须**一条都没有 —— 这条更重要。
     哪天有人给 `get_review_timing` 补了训练样本，L3 就悄悄不再是留出层，
     而「八成提升来自 L3」这句话会变成假的，**报告照样绿**。

`check_eval_leak` 查的是「考卷模板有没有混进训练池」，`split.assert_no_leak`
查的是「这一版切分自己有没有泄漏」——**两个都不问「考的东西训过没有」**。
这是 5.80 那一族：两道闸门各管一半，中间那条缝正好是这次踩的。

📌 「训了但考卷量不到」只报不判：考卷配额是数据设计决定的，
   `get_weak_prerequisites`（训练 48 条 / 考卷 0 道）不是缺陷，是取舍。
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from esa.evalset import L3_HOLDOUT_PREFIXES  # noqa: E402

EVAL_DIR = HERE.parent / "data" / "eval"


def _load_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.is_file():
        sys.exit(f"❌ 缺文件：{path} —— 先跑 esa.evalset")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _train_calls(sample: dict) -> set[str]:
    """训练样本里被调用过的工具名。gold 就是 turns 本身，没有单独的 expected_tools。"""
    out: set[str] = set()
    for turn in sample.get("turns") or []:
        for call in turn.get("calls") or []:
            name = call.get("name") if isinstance(call, dict) else None
            if name:
                out.add(name)
    return out


def collect(train_ir: list[dict], exams: dict[str, list[dict]]) -> dict[str, dict]:
    """按工具汇总：考卷道数 / 考卷模板数 / 训练样本数 / 训练模板数。"""
    per: dict[str, dict] = defaultdict(
        lambda: {"eval_q": 0, "eval_tpl": set(), "train_n": 0, "train_tpl": set(),
                 "supp_q": 0}
    )
    for sample in train_ir:
        for tool in _train_calls(sample):
            per[tool]["train_n"] += 1
            per[tool]["train_tpl"].add(sample["template_id"])
    for suite, rows in exams.items():
        key = "supp_q" if suite == "supp" else "eval_q"
        for row in rows:
            gold = row["gold"]
            for tool in gold.get("expected_tools") or []:
                per[tool][key] += 1
                if suite == "main":
                    per[tool]["eval_tpl"].add(gold["template_id"])
    return per


def held_out(tool: str) -> bool:
    """这个工具是不是被 evalset 明确留出当 L3 的。

    判据用**工具名 + `__`**：`L3_HOLDOUT_PREFIXES` 里存的是 template 前缀
    （`get_review_timing__`），而模板名的头一段就是工具名。这里不另写一份清单 ——
    多写一份就会有第三个地方需要同步（5.17 那一族）。
    """
    return any(p.rstrip("_").split("__")[0] == tool for p in L3_HOLDOUT_PREFIXES)


def check(per: dict[str, dict]) -> list[str]:
    """返回硬性问题清单；空列表 = 通过。"""
    bad: list[str] = []
    for tool, v in sorted(per.items()):
        exam = v["eval_q"] + v["supp_q"]
        if exam and v["train_n"] == 0 and not held_out(tool):
            bad.append(
                f"{tool}：考卷 {exam} 道，训练池 0 条，而它**不在** "
                f"L3_HOLDOUT_PREFIXES 里 —— 要么是切分把它整族漏到考卷侧了"
                f"（那是缺陷），要么是有意留出（那就把前缀加进 evalset）"
            )
        if held_out(tool) and v["train_n"]:
            bad.append(
                f"{tool}：它是 L3 留出层，训练池里却有 {v['train_n']} 条 —— "
                f"L3 从此不再是「未见工具」，而「提升多少来自 L3」这句话会变成假的，"
                f"报告却照样绿。要么删掉这些训练样本，要么把它从 "
                f"L3_HOLDOUT_PREFIXES 拿掉并重画分层图"
            )
    return bad


def _self_test() -> int:
    """反向验证：造两个假分配，闸门必须分别报出来。"""
    real = next((p.rstrip("_").split("__")[0] for p in L3_HOLDOUT_PREFIXES), None)
    if real is None:
        print("  ⚠️ L3_HOLDOUT_PREFIXES 是空的，跳过反向验证的第二条")
    cases = [
        ("考卷有、训练零、又没留出",
         {"some_new_tool": {"eval_q": 12, "supp_q": 0, "train_n": 0,
                            "eval_tpl": set(), "train_tpl": set()}}),
    ]
    if real:
        cases.append(
            ("留出的工具被补了训练样本",
             {real: {"eval_q": 49, "supp_q": 0, "train_n": 30,
                     "eval_tpl": set(), "train_tpl": set()}}))
    bad = 0
    for label, fake in cases:
        if not check(fake):
            print(f"  ❌ 反向验证失败：{label} —— 闸门没报")
            bad += 1
        else:
            print(f"  ✅ 反向验证：{label} —— 报了")
    # 正向：留出的工具训练零，不该报
    if real and check({real: {"eval_q": 49, "supp_q": 0, "train_n": 0,
                              "eval_tpl": set(), "train_tpl": set()}}):
        print("  ❌ 反向验证失败：留出且训练为零，闸门不该报")
        bad += 1
    else:
        print("  ✅ 反向验证：留出且训练为零 —— 没报（对）")
    return bad


def main() -> int:
    train_ir = _load_jsonl(EVAL_DIR / "train_ir.jsonl")
    exams = {"main": _load_jsonl(EVAL_DIR / "eval.jsonl"),
             "supp": _load_jsonl(EVAL_DIR / "eval_supp.jsonl")}
    per = collect(train_ir, exams)

    print(f"{'工具':30s}{'考卷':>6s}{'补充':>6s}{'训练':>6s}{'考卷模板':>9s}{'训练模板':>9s}")
    for tool, v in sorted(per.items(), key=lambda x: (-x[1]["eval_q"], x[0])):
        mark = "  "
        if held_out(tool):
            mark = "🔒"                      # L3 留出，训练零是对的
        elif (v["eval_q"] + v["supp_q"]) == 0 and v["train_n"]:
            mark = "⚪"                      # 训了但量不到，只报不判
        print(f"{mark}{tool:28s}{v['eval_q']:6d}{v['supp_q']:6d}{v['train_n']:6d}"
              f"{len(v['eval_tpl']):9d}{len(v['train_tpl']):9d}")
    print("   🔒 = evalset.L3_HOLDOUT_PREFIXES 明确留出的「未见工具」，训练池必须为零")
    print("   ⚪ = 训了但考卷量不到 —— 只报不判，考卷配额是数据设计决定的")

    unmeasured = sorted(t for t, v in per.items()
                        if (v["eval_q"] + v["supp_q"]) == 0 and v["train_n"])
    if unmeasured:
        n = sum(per[t]["train_n"] for t in unmeasured)
        print(f"\n📌 训了但考卷一道都量不到的工具 {len(unmeasured)} 个、共 {n} 条训练样本："
              f"{unmeasured}")

    print("\n── 反向验证 ──")
    if _self_test():
        return 1

    problems = check(per)
    if problems:
        print(f"\n❌ {len(problems)} 处工具分配不是有意的：")
        for p in problems:
            print(f"   · {p}")
        return 1
    locked = sorted(t for t in per if held_out(t))
    print(f"\n✅ 工具分配都是有意的：考卷考到的工具训练池都有，"
          f"L3 留出的 {locked} 训练池为零")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
