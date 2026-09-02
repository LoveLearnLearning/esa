"""把两份 `report_*.json` 压成「画三张图需要的那点数」。

为什么单独一个模块
------------------
**本机连不上超算，`scp` / `rsync` 都不通，同步只能靠粘贴**（手册 3350）。
147 KB 的 report 粘不回来，所以「本机直接读 report 画图」这条路走不通。

于是拆成两半，而**算的那份只写一遍**：

    集群：tools/export_figure_data.py  → 印一小段 JSON（几 KB，粘得回来）
    本机：tools/make_result_figures.py → 读那段 JSON 画图

这也正是手册那条原则：「产物往本机走：贴输出。所以脚本要**主动把关键结论
印出来**，而不是只写文件 —— 写进文件的东西助手看不见。」

⚠️ 这里不 import matplotlib：集群那半边不画图，不该被绘图依赖挡住。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from esa.eval import LOWER_IS_BETTER, TARGETS, paired_stats

SCHEMA = "esa.figure_data.v1"


def rate(rep: dict, k: str, drop: frozenset[str]) -> tuple[float, int, int] | None:
    """这一项的比率，摘掉 `drop` 之后重算。

    ⚠️ 不用 `_stats` 的 num/den —— 那是全量算的，摘题之后就不对了。
    改从 `_items` 现算，摘除才真的生效。
    """
    items = {i: v for i, v in rep.get("_items", {}).get(k, {}).items() if i not in drop}
    if not items:
        return None
    num = sum(1 for v in items.values() if v)
    return num / len(items) * 100, num, len(items)


def build(rb: dict, rl: dict, base_tag: str, lora_tag: str, *,
          layer_of: dict[str, str] | None = None,
          action_of: dict[str, str] | None = None,
          drop: frozenset[str] = frozenset(),
          drop_reason: str = "") -> dict[str, Any]:
    """两份报告 → 画图要的全部数字。

    `drop` 必须**对两个模型同时生效**（题是被摘掉的，不是某个模型被免考）。
    `layer_of` / `action_of` 是题号 → 层 / → 期望动作，用来出分层图和构成表。
    """
    paired = {r["metric"]: r for r in paired_stats(rb, rl, drop)}

    M = []
    for k, (target, direction) in TARGETS.items():
        a, b = rate(rb, k, drop), rate(rl, k, drop)
        if a is None or b is None:
            continue        # 这一项没有题（或全摘光了），画进去只会误导
        row = paired.get(k)
        # ⚠️ 这里**不要**把 LOWER_IS_BETTER 的比率翻成 100-x。
        # 图的契约是「原始比率 + dir 表示方向」，目标线按原始值画
        # （误触发率的目标是 ≤5，翻过来就变成一条画在 5 的线配一个 95 的点）。
        # 翻方向只发生在 fig3 的「谁答对了」那张，因为那里画的是题数不是比率。
        va, vb = a[0], b[0]
        M.append({
            "metric": k, "base": va, "lora": vb,
            "base_n": [a[1], a[2]], "lora_n": [b[1], b[2]],
            "target": target, "dir": "hi" if direction == "ge" else "lo",
            "p": row["p"] if row else 1.0,
            "only_base": row["only_a"] if row else 0,
            "only_lora": row["only_b"] if row else 0,
            "lower_is_better": k in LOWER_IS_BETTER,
        })

    L = []
    if layer_of:
        for layer in sorted(set(layer_of.values())):
            ids = {i for i, v in layer_of.items() if v == layer} - drop
            out = []
            for rep in (rb, rl):
                items = {i: v for i, v in
                         rep.get("_items", {}).get("工具选择准确率", {}).items()
                         if i in ids}
                out.append((sum(items.values()), len(items)) if items else None)
            if None in out:
                continue    # 这一层没有「该调工具」的题
            (bn, bd), (ln, ld) = out
            L.append({"layer": layer, "base": bn / bd * 100, "lora": ln / ld * 100,
                      "base_n": [bn, bd], "lora_n": [ln, ld]})

    comp: dict[str, dict[str, int]] = {}
    if action_of:
        comp["expected_action"] = dict(Counter(
            v for i, v in action_of.items() if i not in drop))
    if layer_of:
        comp["layer"] = dict(Counter(
            v for i, v in layer_of.items() if i not in drop))

    return {
        "schema": SCHEMA,
        "base_tag": base_tag, "lora_tag": lora_tag,
        "n_scored": (M[0]["base_n"][1] if M else 0),
        "n_dropped": len(drop),
        "drop_reason": drop_reason,
        "composition": comp,
        "M": M, "L": L,
    }
