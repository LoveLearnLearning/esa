#!/usr/bin/env python3
"""从隐状态里找「该不该调工具」那个方向，并报它在**考卷上**的可分性（AUROC）。

配套 `dump_hidden_states.py`。回答的问题只有一个：

> 误触发到底是**知识问题**（模型不知道这题不该调），
> 还是**解码/校准问题**（模型内部分得清，只是没把它变成决策）？

如果后者成立，[arXiv 2608.25198] 那条推理期方向干预就有前提，
而且它不用训练 —— 对一个「多训也不动」的指标来说，这是目前唯一一条新路。
如果 AUROC 只有 0.6 出头，那条路就直接排除，省下一轮 DPO。

🔴 方向怎么取：**差值均值（difference-of-means）**，不拟合分类器。
   这是那篇论文自己用的取法（"extracted without any training"），
   也避免了「用一个训出来的探针去证明信息存在」那种自证。

🔴 拟合集和测试集必须分开：方向在**训练侧探针集**上算，AUROC 在**考卷**上报。
   在考卷上算方向再在考卷上报数 = 拿考卷训练，数字没有意义。

用法
----
    python tools/probe_tool_direction.py \\
        --fit  $HOME/esa_results/hidden_probe_ep10.npz \\
        --test $HOME/esa_results/hidden_main_ep10.npz
    python tools/probe_tool_direction.py --self-test
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import numpy as np


def auroc(scores: np.ndarray, labels: np.ndarray) -> float:
    """Mann-Whitney U 版 AUROC。不用 sklearn（集群那个环境里没有）。

    并列名次用平均秩处理 —— 不处理的话，一堆相同分数会让结果偏向 0 或 1。
    """
    pos, neg = labels == 1, labels == 0
    n_pos, n_neg = int(pos.sum()), int(neg.sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores), dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1, dtype=float)
    # 并列取平均秩
    s = scores[order]
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and s[j + 1] == s[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = ranks[order[i:j + 1]].mean()
        i = j + 1
    return (ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def direction(feats: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """差值均值方向，逐层。feats: (N, L, H) → (L, H)，已归一化。"""
    pos = feats[labels == 1].astype(np.float32).mean(axis=0)
    neg = feats[labels == 0].astype(np.float32).mean(axis=0)
    d = pos - neg
    norm = np.linalg.norm(d, axis=-1, keepdims=True)
    return d / np.maximum(norm, 1e-8)


def _self_test() -> int:
    """反向验证：造三种数据，AUROC 必须分别落在该落的地方。"""
    rng = np.random.default_rng(20260904)
    n, L, H = 400, 3, 64
    ok = 0
    cases = []

    # ① 真有方向：正类沿 e0 平移
    lab = (rng.random(n) < 0.5).astype(np.int8)
    x = rng.normal(size=(n, L, H)).astype(np.float32)
    x[lab == 1, :, 0] += 3.0
    d = direction(x[:200], lab[:200])
    sc = np.einsum("nh,h->n", x[200:, -1], d[-1])
    a = auroc(sc, lab[200:])
    cases.append(("有方向 → AUROC 应 >0.9", a, a > 0.9))

    # ② 纯噪声：不该分得开
    lab2 = (rng.random(n) < 0.5).astype(np.int8)
    x2 = rng.normal(size=(n, L, H)).astype(np.float32)
    d2 = direction(x2[:200], lab2[:200])
    sc2 = np.einsum("nh,h->n", x2[200:, -1], d2[-1])
    a2 = auroc(sc2, lab2[200:])
    cases.append(("纯噪声 → AUROC 应在 0.5 附近（0.35~0.65）", a2, 0.35 < a2 < 0.65))

    # ③ 全部并列同分 → 必须是 0.5，不能因为并列滑到 0 或 1
    a3 = auroc(np.zeros(10), np.array([1, 1, 1, 1, 1, 0, 0, 0, 0, 0]))
    cases.append(("全部同分 → 必须正好 0.5", a3, abs(a3 - 0.5) < 1e-9))

    for name, val, passed in cases:
        print(f"{'✅' if passed else '❌'} {name}（实测 {val:.3f}）")
        ok += bool(passed)
    print(f"\n{ok} 通过 / {len(cases) - ok} 失败")
    return 0 if ok == len(cases) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    if "--self-test" in sys.argv[1:]:
        return _self_test()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--fit", required=True, nargs="+",
                    help="算方向用（训练侧探针集）。可以给多份 —— "
                         "eval_probe 里一道 CALL_TOOL 都没有（它只有 clarify/"
                         "hard_negative/refusal 三类），正类得从 eval_probe_tool 来，"
                         "所以这两份必须一起给，否则差值均值算不出方向")
    ap.add_argument("--test", required=True, help="报 AUROC 用（考卷）")
    ap.add_argument("--export", default=None,
                    help="把方向向量 + 阈值表导出成一个 npz，供推理侧当闸门用。"
                         "只导**最好那一层**——多导几层只会让下游选错")
    a = ap.parse_args()

    T = np.load(a.test, allow_pickle=True)
    parts = [np.load(f, allow_pickle=True) for f in a.fit]
    for f, P in zip(a.fit, parts):
        if not np.array_equal(P["layers"], T["layers"]):
            sys.exit(f"❌ {f} 的层号与测试集对不上，不能比")
        if str(P["adapter"]) != str(T["adapter"]):
            sys.exit(f"❌ {f} 不是同一个模型：{P['adapter']} vs {T['adapter']}\n"
                     "   方向是模型的属性，跨模型算等于量了另一个东西")
    F = {
        "feats": np.concatenate([P["feats"] for P in parts]),
        "labels": np.concatenate([P["labels"] for P in parts]),
        "layers": parts[0]["layers"],
        "adapter": parts[0]["adapter"],
        "suite": "+".join(str(P["suite"]) for P in parts),
    }
    if (F["labels"] == 1).sum() == 0 or (F["labels"] == 0).sum() == 0:
        sys.exit("❌ 拟合集里只有一类，差值均值算不出方向 —— "
                 "把 eval_probe（负类）和 eval_probe_tool（正类）一起给")
    layers = F["layers"]
    print(f"模型 {F['adapter']}")
    print(f"  拟合集 {F['suite']}：{len(F['labels'])} 道"
          f"（该调 {int((F['labels'] == 1).sum())} / 不该调 {int((F['labels'] == 0).sum())}）")
    print(f"  测试集 {T['suite']}：{len(T['labels'])} 道"
          f"（该调 {int((T['labels'] == 1).sum())} / 不该调 {int((T['labels'] == 0).sum())}）")

    d = direction(F["feats"], F["labels"])
    print(f"\n{'层':>6s}{'考卷 AUROC':>12s}{'拟合集自身':>12s}   ← 后者只是对照，别当结论")
    best = (0.0, None)
    for i, layer in enumerate(layers):
        s_test = np.einsum("nh,h->n", T["feats"][:, i].astype(np.float32), d[i])
        s_fit = np.einsum("nh,h->n", F["feats"][:, i].astype(np.float32), d[i])
        a_test, a_fit = auroc(s_test, T["labels"]), auroc(s_fit, F["labels"])
        mark = " ⭐" if a_test > best[0] else ""
        if a_test > best[0]:
            best = (a_test, int(layer))
        print(f"{int(layer):6d}{a_test:12.3f}{a_fit:12.3f}{mark}")

    print(f"\n最好的一层：第 {best[1]} 层，考卷 AUROC = {best[0]:.3f}")
    print("判读：")
    print("  ≥0.85  模型内部分得清 → 误触发是**校准问题**，"
          "2608.25198 那条推理期方向干预有前提，值得跟后端提")
    print("  0.7~0.85  部分可分 —— 能当辅助信号，但单靠它不够")
    print("  <0.7   分不开 → 这条路线直接排除，省下一轮 DPO 的成本")

    if a.export:
        i = list(layers).index(best[1])
        st = np.einsum("nh,h->n", T["feats"][:, i].astype(np.float32), d[i])
        yt = T["labels"]
        # 阈值表：按 gold 该调那一组的分位数取。低于阈值就压制调用。
        # 报「保住多少正常调用」，因为那才是这个闸门的代价。
        rows = [(float(q), float(np.quantile(st[yt == 1], q)),
                 float((st[yt == 1] >= np.quantile(st[yt == 1], q)).mean()))
                for q in (0.02, 0.05, 0.10, 0.20, 0.30)]
        np.savez(a.export,
                 direction=d[i].astype(np.float32), layer=np.int32(best[1]),
                 auroc=np.float32(best[0]),
                 thresholds=np.array([r[1] for r in rows], dtype=np.float32),
                 keep_call_rate=np.array([r[2] for r in rows], dtype=np.float32),
                 quantile=np.array([r[0] for r in rows], dtype=np.float32),
                 # 🔴 只存目录名。存全路径会把 /persist_data/home/<账号> 带进
                 # 要发布的产物里，而泄漏扫描只查文本后缀，**扫不到 .npz**。
                 adapter=pathlib.PurePosixPath(str(T["adapter"])).name,
                 fit_suite=F["suite"], test_suite=str(T["suite"]))
        print(f"\n✅ 方向已导出 → {a.export}"
              f"（第 {best[1]} 层，{d[i].shape[0]} 维，AUROC {best[0]:.3f}）")
        print("   阈值表（低于阈值就压制调用）：")
        for q, thr, keep in rows:
            print(f"     分位 {q:.2f}  阈值 {thr:+9.3f}  正常调用保住 {keep * 100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
