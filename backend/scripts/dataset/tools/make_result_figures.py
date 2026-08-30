"""⑤ 微调结果的三张图 —— 《06—效果验证报告》用。

    python3 dataset/tools/make_result_figures.py
    → dataset/docs/figures/fig{1,2,3}_*.png

数字的来源（**这一条最要紧**）
------------------------------
🔴 **2026-08-27 改成直接读 `report_*.json`，手抄那一环已经删掉。**

在此之前 `M` / `L` / `PAIR` 三张表是从 `esa.eval compare` 的输出逐个抄进来的，
而抄下来的表会漂：抄的是 **78907**（2026-08-20），定版早已换成 80269，
中间还隔着 79803 —— **三张图整整旧了两代，而它们是准备直接嵌进《06》的**。
判据里写着「作业号变了而表没变，图就是旧的」，但没有任何东西会去查那个作业号。

现在：达标线与方向从 `esa.eval.TARGETS` 取，百分比从 `_stats` 的 `num/den` 算，
配对检验从 `esa.eval.paired_stats()` 算（那个函数 2026-08-27 从 `print_paired`
里拆出来，就是为了不在这里再写第二遍 —— 5.54）。

    python3 dataset/tools/make_result_figures.py \
        --reports dataset/data/eval --base base --lora 85362

**报告不在就直接报错退出**，不画图。以前那种「拿旧常量画一张看起来正常的图」
才是最危险的失效方式：图上没有任何地方会告诉你它是旧的。

⚠️ 汇总数一律现算，不许手写：第一版 fig3 的标题手写成「205 道 / 9 道」，
实际是 215 / 12。一张图的标题里放一个凭印象写的数字，和编数据没有区别。

配色
----
取 dataviz 参考调色板的 categorical slot 1（蓝 #2a78d6）与 slot 2（橙 #eb6834），
跑过 `validate_palette.py --mode light`，五项全 PASS：
CVD ΔE 24.7（门槛 ≥8）、常视 ΔE 33.6（门槛 ≥15）、对比度均 ≥3:1。
⚠️ base 恒为蓝、lora 恒为橙，三张图一致。别按「哪个更好看」临时换。

只做浅色版：这三张图的去处是提交的报告文档，不是网页。
"""
import argparse
import json
import sys
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


ap = argparse.ArgumentParser(description="从 report_*.json 画《06》那三张图")
ap.add_argument("--reports", type=Path, default=Path("dataset/data/eval"),
                help="放 report_<tag>.json 的目录")
ap.add_argument("--base", default="base", help="未微调那一版的 tag")
ap.add_argument("--lora", help="微调后那一版的 tag，例如 80269；给了 --data 就不用")
ap.add_argument("--data", type=Path, default=None,
                help="集群上 export_figure_data.py 印出来、粘回本机的那段 JSON")
# 🔴 2026-08-27 加：冒烟测试拿合成报告跑了一遍，直接把 docs/figures 里的
# 交付图覆盖成了假数据（靠 git checkout 才捞回来）。写死落点的脚本，
# 一旦被拿去试跑就会毁掉交付物 —— 试跑时用 --out 指到别处。
ap.add_argument("--out", type=Path, default=None,
                help="图的落点；不给就写进 dataset/docs/figures（交付位置）")
args = ap.parse_args()

OUT = args.out or (Path(__file__).resolve().parents[1] / "docs" / "figures")
OUT.mkdir(parents=True, exist_ok=True)   # 目录不入库（只有 png 入），跑之前自己建

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from esa.eval import SMALL_N  # noqa: E402
from esa.figure_data import SCHEMA as FD_SCHEMA  # noqa: E402
from esa.figure_data import build as fd_build  # noqa: E402


def load_report(tag: str) -> dict:
    f = args.reports / f"report_{tag}.json"
    if not f.exists():
        raise SystemExit(
            f"❌ 报告不在：{f}\n"
            "   判分产物按设计不入库，要从集群拷回本机：\n"
            f"     scp <集群>:/persist_data/home/chenxuzhao/esa_results/report_{tag}.json {args.reports}/\n"
            "   ⚠️ 别退回旧常量画图 —— 一张画错了却看起来正常的图，比没有图糟。"
        )
    return json.loads(f.read_text(encoding="utf-8"))


if args.data:
    DATA = json.loads(args.data.read_text(encoding="utf-8"))
    if DATA.get("schema") != FD_SCHEMA:
        raise SystemExit(f"❌ {args.data} 不是 {FD_SCHEMA}（是 {DATA.get('schema')!r}）"
                         " —— 版本对不上就别画，重跑 export_figure_data.py")
else:
    if not args.lora:
        raise SystemExit("❌ 要么给 --data，要么给 --lora（从本地 report 现算）")
    recs = [json.loads(x) for x in
            (args.reports / "eval.jsonl").open(encoding="utf-8") if x.strip()]
    DATA = fd_build(load_report(args.base), load_report(args.lora),
                    args.base, args.lora,
                    layer_of={r["gold"]["id"]: r["gold"].get("layer") for r in recs
                              if r["gold"].get("layer")},
                    action_of={r["gold"]["id"]: r["gold"].get("expected_action")
                               for r in recs if r["gold"].get("expected_action")})

BASE_TAG, LORA_TAG = DATA["base_tag"], DATA["lora_tag"]

# 指标, base, lora, 目标, 方向(hi=越高越好), p 值 —— 全部来自 figure_data，
# 这里一个数都不算，免得两处各算一遍又分叉（5.54）。
M = [(m["metric"], m["base"], m["lora"], m["target"], m["dir"], m["p"],
      m["lora_n"][1]) for m in DATA["M"]]
if not M:
    raise SystemExit("❌ 没有任何一项有题 —— 是不是 tag 弄错了？")
# 分层
L = [(x["layer"].replace("_", " "), x["base"], x["lora"],
      f'{x["base_n"][0]}/{x["base_n"][1]}', f'{x["lora_n"][0]}/{x["lora_n"][1]}')
     for x in DATA["L"]]
# 配对：只有一方答对的题数。「1=失败」的两项在 figure_data 里已经翻好方向了，
# 这里再翻一次就是翻回去 —— 别动。
PAIR = [(m["metric"], m["only_base"], m["only_lora"], m["p"]) for m in DATA["M"]]
PAIR = [(n, (ob if not lb else ol), (ol if not lb else ob), pv)
        for (n, ob, ol, pv), lb in
        zip(PAIR, [m["lower_is_better"] for m in DATA["M"]])]
PAIR.sort(key=lambda t: t[2] - t[1], reverse=True)
M.sort(key=lambda m: (m[1] - m[2]) if m[4] == "lo" else (m[2] - m[1]), reverse=True)
if not M:
    raise SystemExit("❌ 两份报告里没有任何一项同时有题 —— 是不是 tag 弄错了？")


def dumbbell(ax, rows, title):
    """哑铃图：一行一个指标，两点连线表示 base → lora 的移动。"""
    ys = range(len(rows))
    for y, (name, b, la, tgt, _d, p, _den) in zip(ys, rows):
        ax.plot([b, la], [y, y], color=MUTED, lw=2, zorder=1,
                solid_capstyle="round")
        # 两值相同时橙点会把蓝点完全盖住，看上去像 base 没有数 ——
        # 把 base 画大一圈，露出一圈蓝边（2026-08-27 看图时发现）。
        ax.scatter([b], [y], s=260 if abs(b - la) < 0.05 else 90, color=BASE,
                   zorder=3, edgecolors="#fcfcfb", linewidths=2)
        ax.scatter([la], [y], s=90, color=LORA, zorder=4,
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
    # 🔴 小分母必须标在图上。一张交付用的图里放一个 n=2 的「100.0」，
    # 是会被评审直接抓住的。门槛用 eval.py 的 SMALL_N（30），不另立标准。
    def _label(row):
        name, _b, _l, _t, _d, p, den = row
        return (name + (" ★" if p < 0.05 else "")
                + (f"（n={den}）" if den < SMALL_N else ""))
    ax.set_yticklabels([_label(r) for r in rows], fontsize=10.5, color=INK)
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
dumbbell(axes[0], hi, f"越高越好（{len(hi)} 项）")
dumbbell(axes[1], lo, f"越低越好（{len(lo)} 项）")
handles = [
    Line2D([], [], marker="o", ls="", ms=9, color=BASE, label="base（未微调）"),
    Line2D([], [], marker="o", ls="", ms=9, color=LORA, label="lora（微调后）"),
    Line2D([], [], color=INK2, lw=1.4, alpha=.55, label="达标线"),
]
fig.legend(handles=handles, loc="lower center", frameon=False,
           fontsize=9.5, labelcolor=INK2, ncol=3, bbox_to_anchor=(0.55, 0.0))
# 题数与 tag 都现算 —— 原来这里写死「443 道题」和「后端基准 2aea243」，
# 考卷早就换成 456 道了，而图上没有任何地方会告诉你这件事。
_N = DATA["n_scored"]
_DROP = f"，已摘 {DATA['n_dropped']} 道" if DATA["n_dropped"] else ""
fig.suptitle(f"{len(M)} 项指标：{BASE_TAG} → {LORA_TAG}（{_N} 道题{_DROP}）",
             fontsize=14, color=INK, x=0.012, ha="left", y=0.985)
fig.text(0.012, 0.945,
         "★ = 逐题配对 McNemar 精确检验 p<0.05　·　同一套题、同一判分器、"
         "temperature=0，唯一变量是模型",
         fontsize=9, color=INK2, ha="left")
fig.tight_layout(rect=[0, 0.055, 1, 0.925])
fig.savefig(f"{OUT}/fig1_十二项对比.png", dpi=200)
plt.close(fig)

# ── 图 2：分层 ──
# 分层：层名直接用报告里的键，别写死 L1/L2/L3 ——
# 探针集那套报告里层名是 TRAIN_PROBE，写死就会画出一张空图。
fig, ax = plt.subplots(figsize=(9.6, 3.5))
for y, (name, b, la, bn, ln) in enumerate(L):
    ax.plot([b, la], [y, y], color=MUTED, lw=2, zorder=1, solid_capstyle="round")
    ax.scatter([b], [y], s=300 if abs(b - la) < 0.05 else 110, color=BASE,
               zorder=3, edgecolors="#fcfcfb", linewidths=2)
    ax.scatter([la], [y], s=110, color=LORA, zorder=4,
               edgecolors="#fcfcfb", linewidths=2)
    ax.annotate(f"{b:.1f}  {bn}", (b, y), textcoords="offset points",
                xytext=(-9, 0), ha="right", va="center", fontsize=9.5, color=INK2)
    ax.annotate(f"{la:.1f}  {ln}", (la, y), textcoords="offset points",
                xytext=(9, 0), ha="left", va="center",
                fontsize=10, color=INK, weight="bold")
ax.set_yticks(range(len(L)))
ax.set_yticklabels([n for n, *_ in L], fontsize=10.5, color=INK)
ax.set_ylim(len(L) - 0.5, -0.5)
ax.set_xlim(-16, 118)
ax.set_xticks([0, 20, 40, 60, 80, 100])
ax.set_xlabel("工具选择准确率 %", fontsize=9, color=INK2)
ax.grid(axis="x", color="#e6e5e0", lw=1, zorder=0)
ax.set_axisbelow(True)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.spines["bottom"].set_color("#e6e5e0")
ax.tick_params(axis="both", length=0, colors=INK2)
_NET = {x["layer"]: x["lora_n"][0] - x["base_n"][0] for x in DATA["L"]}
_L3 = next((v for k, v in _NET.items() if k.startswith("L3")), 0)
# 净提升与 L3 占比都现算 —— 原来这两个数写死在标题里（45 / 36），
# 那是 78907 时代抄下来的，两代之后还印在准备交付的图上。
ax.set_title(f"分层看：净提升 {sum(_NET.values())} 道里，{_L3} 道来自零样本留出组 L3",
             fontsize=13, color=INK, loc="left", pad=12)
# ⚠️ 图上的文字 matplotlib 不认 markdown，`**` 会被原样画出来；
# emoji 也没有字形，渲染成豆腐块。这里一律用纯文本。
# 也别把「写给我们自己的提醒」印上去 —— 图是给评审看的。
fig.text(0.012, 0.02,
         "L3 = get_review_timing 整组留出：训练集里仅 1 条，"
         "且教的是「重试时改参数」而不是「什么意图该选这个工具」。",
         fontsize=9, color=INK2, ha="left")
fig.tight_layout(rect=[0, 0.07, 1, 1])
fig.savefig(f"{OUT}/fig2_分层.png", dpi=200)
plt.close(fig)

# ── 图 3：配对检验。1=失败的两项要翻过来，统一成「谁答对了」──
_PMAX = max([max(t[1], t[2]) for t in PAIR] or [0])
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
    # ⚠️ x 位置按最长的柱子现算。原来写死 60，而这一轮最长柱是 61 ——
    # p 值标签直接压在柱子的数字上。**图上任何写死的坐标都会被数据涨出去。**
    ax.annotate(tag + ("  ★" if p < .05 else ""), (_PMAX + 6, y),
                ha="left", va="center", fontsize=9,
                color=INK if p < .05 else MUTED)
ax.axvline(0, color=INK2, lw=1.2, zorder=3)
ax.set_yticks(range(len(PAIR)))
ax.set_yticklabels([n for n, *_ in PAIR], fontsize=10.5, color=INK)
ax.set_ylim(len(PAIR) - 0.5, -0.5)
ax.set_xlim(-(_PMAX * 0.28 + 6), _PMAX + 34)
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
