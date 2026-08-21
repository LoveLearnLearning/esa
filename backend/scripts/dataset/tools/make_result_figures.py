"""⑤ 微调结果的三张图 —— 《06—效果验证报告》用。

    python3 dataset/tools/make_result_figures.py
    → dataset/docs/figures/fig{1,2,3}_*.png

数字的来源（**这一条最要紧**）
------------------------------
下面 `M` / `L` / `PAIR` 三张表是 2026-08-20 从超算上
`esa.eval compare --tags base lora` 的输出**逐个抄下来的**
（训练作业 78907、base 评测 79039、lora 评测 79040，主评测集 443 道）。

⚠️ 手抄就会漂。**重跑评测之后必须回来更新这三张表**，
判断依据是每张表旁边记的作业号 —— 作业号变了而表没变，图就是旧的。
⚠️ 而且**汇总数一律从表里现算，不许手写**：第一版 fig3 的标题手写成
「205 道 / 9 道」，实际是 215 / 12。一张图的标题里放一个凭印象写的数字，
和编数据没有区别。现在标题里的两个数由 `sum()` 得出。

📌 报告产物在超算上（`esa_results/report_*.json`），本机没有。
哪天把它们拷回本机，这个脚本应当改成直接读 `_stats`，把手抄这一环去掉。

配色
----
取 dataviz 参考调色板的 categorical slot 1（蓝 #2a78d6）与 slot 2（橙 #eb6834），
跑过 `validate_palette.py --mode light`，五项全 PASS：
CVD ΔE 24.7（门槛 ≥8）、常视 ΔE 33.6（门槛 ≥15）、对比度均 ≥3:1。
⚠️ base 恒为蓝、lora 恒为橙，三张图一致。别按「哪个更好看」临时换。

只做浅色版：这三张图的去处是提交的报告文档，不是网页。
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

plt.rcParams.update({
    "font.sans-serif": ["Hiragino Sans GB", "STHeiti", "Songti SC", "Arial Unicode MS"],
    "axes.unicode_minus": False,
    "figure.facecolor": "#fcfcfb",
    "axes.facecolor": "#fcfcfb",
    "savefig.facecolor": "#fcfcfb",
})

BASE, LORA = "#2a78d6", "#eb6834"      # categorical slot 1 / 2
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#b8b7b0"
OUT = Path(__file__).resolve().parents[1] / "docs" / "figures"
OUT.mkdir(parents=True, exist_ok=True)   # 目录不入库（只有 png 入），跑之前自己建

# 指标, base, lora, 目标, 方向(hi=越高越好), p 值
M = [
    ("追问命中率",          23.3, 100.0, 90,  "hi", 0.0000),
    ("结果忠实度",          69.1, 100.0, 98,  "hi", 0.0000),
    ("工具选择准确率",      64.2,  91.5, 90,  "hi", 0.0000),
    ("工具调用完全正确率",  48.5,  79.4, 85,  "hi", 0.0000),
    ("工具失败恢复率",      62.5,  93.8, 90,  "hi", 0.0625),
    ("拒绝命中率",          83.3, 100.0, 100, "hi", 1.0000),
    ("参数完全匹配率",      75.5,  86.8, 85,  "hi", 0.0010),
    ("结果响应率",          95.7,  99.4, 95,  "hi", 0.0312),
    ("格式合法率",          99.8, 100.0, 100, "hi", 1.0000),
    ("参数schema合法率",   100.0, 100.0, 98,  "hi", 1.0000),
    ("误触发率 FPR",        30.8,  12.3, 5,   "lo", 0.0042),
    ("漏调率 FNR",           6.7,   3.0, 10,  "lo", 0.1460),
]


def dumbbell(ax, rows, title):
    """哑铃图：一行一个指标，两点连线表示 base → lora 的移动。"""
    ys = range(len(rows))
    for y, (name, b, la, tgt, _d, p) in zip(ys, rows):
        ax.plot([b, la], [y, y], color=MUTED, lw=2, zorder=1,
                solid_capstyle="round")
        ax.scatter([b], [y], s=90, color=BASE, zorder=3,
                   edgecolors="#fcfcfb", linewidths=2)
        ax.scatter([la], [y], s=90, color=LORA, zorder=3,
                   edgecolors="#fcfcfb", linewidths=2)
        # 目标线：一个竖短划，不喧宾夺主
        ax.plot([tgt, tgt], [y - 0.32, y + 0.32], color=INK2, lw=1.4,
                alpha=.55, zorder=2)
        # ⚠️ 每个数字钉在**它自己那个点**上，偏移方向按谁在左谁在右决定。
        # 原来写死「base 在左、lora 在右」，于是「越低越好」那两行
        # （lora < base）的两个数字左右对调了 —— 图上 30.8 落在了 lora 的点旁边。
        if abs(b - la) < 0.05:                      # 两值相同，画一个就够
            ax.annotate(f"{la:.1f}", (la, y), textcoords="offset points",
                        xytext=(9, 0), ha="left", va="center",
                        fontsize=9.5, color=INK, weight="bold", bbox=dict(facecolor="#fcfcfb", edgecolor="none", pad=1.2), zorder=4)
        else:
            b_off, l_off = ((-8, 8) if b < la else (8, -8))
            ax.annotate(f"{b:.1f}", (b, y), textcoords="offset points",
                        xytext=(b_off, 0), ha="right" if b < la else "left",
                        va="center", fontsize=9, color=INK2, bbox=dict(facecolor="#fcfcfb", edgecolor="none", pad=1.2), zorder=4)
            ax.annotate(f"{la:.1f}", (la, y), textcoords="offset points",
                        xytext=(l_off, 0), ha="left" if b < la else "right",
                        va="center", fontsize=9.5, color=INK, weight="bold", bbox=dict(facecolor="#fcfcfb", edgecolor="none", pad=1.2), zorder=4)
    ax.set_yticks(list(ys))
    # ★ 只标显著的，不给每一行都挂符号
    ax.set_yticklabels([f"{n} ★" if p < 0.05 else n for n, *_r, p in rows],
                       fontsize=10.5, color=INK)
    ax.set_ylim(len(rows) - 0.5, -0.5)
    ax.set_xlim(-6, 116)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    ax.set_xlabel("%", fontsize=9, color=INK2)
    ax.set_title(title, fontsize=11.5, color=INK, loc="left", pad=10)
    ax.grid(axis="x", color="#e6e5e0", lw=1, zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#e6e5e0")
    ax.tick_params(axis="both", length=0, colors=INK2)


# ── 图 1：十二项，按方向拆两栏（越高越好 / 越低越好不能混在一张尺子上）──
hi = [m for m in M if m[4] == "hi"]
lo = [m for m in M if m[4] == "lo"]
fig, axes = plt.subplots(
    2, 1, figsize=(9.6, 8.0), height_ratios=[len(hi), len(lo)])
dumbbell(axes[0], hi, "越高越好（10 项）")
dumbbell(axes[1], lo, "越低越好（2 项）")
handles = [
    Line2D([], [], marker="o", ls="", ms=9, color=BASE, label="base（未微调）"),
    Line2D([], [], marker="o", ls="", ms=9, color=LORA, label="lora（微调后）"),
    Line2D([], [], color=INK2, lw=1.4, alpha=.55, label="达标线"),
]
fig.legend(handles=handles, loc="lower center", frameon=False,
           fontsize=9.5, labelcolor=INK2, ncol=3, bbox_to_anchor=(0.55, 0.0))
fig.suptitle("十二项指标：base → lora（主评测集 443 道题）",
             fontsize=14, color=INK, x=0.012, ha="left", y=0.985)
fig.text(0.012, 0.945,
         "★ = 逐题配对 McNemar 精确检验 p<0.05　·　同一套题、同一判分器、"
         "temperature=0、后端基准 2aea243，唯一变量是模型",
         fontsize=9, color=INK2, ha="left")
fig.tight_layout(rect=[0, 0.055, 1, 0.925])
fig.savefig(f"{OUT}/fig1_十二项对比.png", dpi=200)
plt.close(fig)

# ── 图 2：分层 ──
L = [("L1 同分布\n（学过的分布）", 88.0, 95.0, "88/100", "95/100"),
     ("L2 状态外推\n（没见过的组合）", 64.3, 78.6, "9/14", "11/14"),
     ("L3 场景外推\n（训练时零样本）", 17.6, 88.2, "9/51", "45/51")]
fig, ax = plt.subplots(figsize=(9.6, 3.5))
for y, (name, b, la, bn, ln) in enumerate(L):
    ax.plot([b, la], [y, y], color=MUTED, lw=2, zorder=1, solid_capstyle="round")
    ax.scatter([b], [y], s=110, color=BASE, zorder=3,
               edgecolors="#fcfcfb", linewidths=2)
    ax.scatter([la], [y], s=110, color=LORA, zorder=3,
               edgecolors="#fcfcfb", linewidths=2)
    ax.annotate(f"{b:.1f}  {bn}", (b, y), textcoords="offset points",
                xytext=(-9, 0), ha="right", va="center", fontsize=9.5, color=INK2)
    ax.annotate(f"{la:.1f}  {ln}", (la, y), textcoords="offset points",
                xytext=(9, 0), ha="left", va="center",
                fontsize=10, color=INK, weight="bold")
ax.set_yticks(range(len(L)))
ax.set_yticklabels([n for n, *_ in L], fontsize=10.5, color=INK)
ax.set_ylim(len(L) - 0.5, -0.5)
ax.set_xlim(-4, 118)
ax.set_xticks([0, 20, 40, 60, 80, 100])
ax.set_xlabel("工具选择准确率 %", fontsize=9, color=INK2)
ax.grid(axis="x", color="#e6e5e0", lw=1, zorder=0)
ax.set_axisbelow(True)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.spines["bottom"].set_color("#e6e5e0")
ax.tick_params(axis="both", length=0, colors=INK2)
ax.set_title("分层看：净提升 45 道里，36 道来自零样本留出组 L3",
             fontsize=13, color=INK, loc="left", pad=12)
fig.text(0.012, 0.02,
         "L3 = get_review_timing 整组留出，训练时一条样本都没给过。"
         "base 把它认成别的工具，光混淆表前八项里就有 34 次；lora 只剩 4 次。",
         fontsize=9, color=INK2, ha="left")
fig.legend(handles=handles[:2], loc="upper right", frameon=False,
           fontsize=9.5, labelcolor=INK2, ncol=2, bbox_to_anchor=(.99, .99))
fig.tight_layout(rect=[0, 0.07, 1, 1])
fig.savefig(f"{OUT}/fig2_分层.png", dpi=200)
plt.close(fig)

# ── 图 3：配对检验。1=失败的两项要翻过来，统一成「谁答对了」──
PAIR = [("结果忠实度", 0, 42, 0.0000), ("工具调用完全正确率", 3, 54, 0.0000),
        ("工具选择准确率", 4, 49, 0.0000), ("追问命中率", 0, 23, 0.0000),
        ("误触发率 FPR", 2, 14, 0.0042), ("参数完全匹配率", 0, 11, 0.0010),
        ("漏调率 FNR", 3, 9, 0.1460), ("结果响应率", 0, 6, 0.0312),
        ("工具失败恢复率", 0, 5, 0.0625), ("拒绝命中率", 0, 1, 1.0000),
        ("格式合法率", 0, 1, 1.0000), ("参数schema合法率", 0, 0, 1.0000)]
fig, ax = plt.subplots(figsize=(9.6, 5.6))
for y, (name, bw, lw_, p) in enumerate(PAIR):
    if bw:
        ax.barh(y, -bw, height=.55, color=BASE, zorder=2)
        ax.annotate(str(bw), (-bw, y), textcoords="offset points",
                    xytext=(-6, 0), ha="right", va="center",
                    fontsize=9.5, color=INK2)
    if lw_:
        ax.barh(y, lw_, height=.55, color=LORA, zorder=2)
        ax.annotate(str(lw_), (lw_, y), textcoords="offset points",
                    xytext=(6, 0), ha="left", va="center",
                    fontsize=10, color=INK, weight="bold")
    tag = f"p={p:.4f}" if p >= .0001 else "p<0.0001"
    ax.annotate(tag + ("  ★" if p < .05 else ""), (60, y),
                ha="left", va="center", fontsize=9,
                color=INK if p < .05 else MUTED)
ax.axvline(0, color=INK2, lw=1.2, zorder=3)
ax.set_yticks(range(len(PAIR)))
ax.set_yticklabels([n for n, *_ in PAIR], fontsize=10.5, color=INK)
ax.set_ylim(len(PAIR) - 0.5, -0.5)
ax.set_xlim(-14, 92)
ax.set_xticks([-10, 0, 10, 20, 30, 40, 50])
ax.set_xticklabels(["10", "0", "10", "20", "30", "40", "50"])
ax.set_xlabel("不一致配对的题数（← base 独对　|　lora 独对 →）",
              fontsize=9, color=INK2)
ax.grid(axis="x", color="#e6e5e0", lw=1, zorder=0)
ax.set_axisbelow(True)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.spines["bottom"].set_color("#e6e5e0")
ax.tick_params(axis="both", length=0, colors=INK2)
# ⚠️ 汇总数从数据现算，别手写。第一版标题手写成「205 道 / 9 道」，
# 实际是 215 / 12 —— 一张图的标题里放一个凭印象写的数字，和编数据没区别。
_lw = sum(x[2] for x in PAIR)
_bw = sum(x[1] for x in PAIR)
ax.set_title(f"逐题配对：{_lw} 道只有 lora 答对，{_bw} 道只有 base 答对",
             fontsize=13, color=INK, loc="left", pad=12)
fig.text(0.012, 0.025,
         "只统计两个模型答得不一样的题（McNemar 的不一致配对）。"
         "误触发率/漏调率原表记 1=失败，这里已翻成「谁答对」，与其余十项同向。",
         fontsize=9, color=INK2, ha="left")
fig.tight_layout(rect=[0, 0.075, 1, 1])
fig.savefig(f"{OUT}/fig3_配对检验.png", dpi=200)
plt.close(fig)
print("三张图已写入", OUT)
