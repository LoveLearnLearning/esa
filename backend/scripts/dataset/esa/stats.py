# backend/scripts/dataset/esa/stats.py

"""判分用的小样本统计：Wilson 区间、宏平均、McNemar 配对检验。

为什么单独成一个模块：`eval.py` 里那十几个百分比，**没有一个带过区间**。
而报告里正在被当成信号讨论的差值，分母是这样的：

    拒绝命中率  6 道题
    追问命中率  32 道题（其中 30 道来自 2 个模板）
    L2 层       58 道题

Bowyer / Aitchison / Ivanova（ICML 2025，arXiv:2503.01747）那篇立场文的题目
就是《别在少于几百个数据点的 LLM 评测里用中心极限定理》，结论两条，直接适用：

1. 小 n 下 **Wilson 区间**覆盖率良好，而 **CLT 区间和 bootstrap 区间都不可信**
   （bootstrap 的实际覆盖率明显低于名义值）；
2. 题目**成簇**时（我们正是：464 道题来自 68 个模板，其中一个模板独占 88 道），
   只有考虑聚类结构的模型才能给出正确覆盖率；至少要把宏平均一并报出来。

⚠️ **不引入 scipy/numpy**。超算是共享账号，纪律是「不装任何包」
（见 `超算操作手册.md` 〇之二）。下面三个函数用标准库 `math` 就能写完，
所以判分随时能在登录节点上跑，不必申请卡、不必排队。
"""

from __future__ import annotations

import math

# 95% 双侧正态分位数。写死而不是算出来，是为了让判分结果逐位可复现。
Z95 = 1.959963984540054


def wilson(num: int, den: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score 区间，返回 (下界, 上界)，单位是**百分比**。

    分母为 0 时返回 (0.0, 100.0) —— 「一道题都没有」的诚实表述是
    「什么都不知道」，不是 0% 也不是 100%。这一条很要紧：
    `rate()` 在分母为 0 时返回 0.0，报告里看起来就像「这项考了 0 分」。

    为什么不用正负 1.96×标准误：p 接近 0 或 1 时那个区间会跑到 [0,1] 之外，
    而我们恰好有好几项就贴在 0% 和 100%（微调后忠实度 160/160）。
    Wilson 天然落在 [0,1] 内，且在小 n 下覆盖率优于精确的 Clopper-Pearson
    （后者过于保守，区间白白变宽）。
    """
    if den <= 0:
        return (0.0, 100.0)
    p = num / den
    z2n = z * z / den
    center = (p + z2n / 2) / (1 + z2n)
    half = (z / (1 + z2n)) * math.sqrt(p * (1 - p) / den + z2n / (4 * den))
    return (round(100.0 * max(0.0, center - half), 1),
            round(100.0 * min(1.0, center + half), 1))


def macro_rate(items: dict[str, int], group_of: dict[str, str]) -> tuple[float, int]:
    """先按组算比率、再对组取平均。返回 (百分比, 组数)。

    `items` 是 {题号: 0/1}，`group_of` 是 {题号: 模板号}。

    为什么必须有这一项：微平均（现在报的那个）等于**按模板大小加权**。
    我们的 `DIRECT_ANSWER` 有 92 道题，其中 88 道是同一个模板
    `S004__仅提及未要求__nofacts` 的改写 —— 于是「误触发率」这个数
    有三分之二的重量压在**一个场景**上，它答的其实是
    「模型在那一个语境里会不会乱调工具」，而不是一个可推广的比率。

    这个口径不是我们发明的：后端自己的检索评测早就这么做，
    理由写在 `backend/agent/rag/evaluation/metrics.py`：
    「按问题计算指标后取宏平均，避免大文档或多答案问题主导结果」。
    两边对齐，对内也讲得通。

    ⚠️ 微平均和宏平均**都要报**，它们回答的不是同一个问题：
    微平均答「随机抽一道题会怎样」，宏平均答「换一个场景还成不成立」。
    只报一个都会误导。
    """
    if not items:
        return (0.0, 0)
    by_group: dict[str, list[int]] = {}
    for item_id, ok in items.items():
        by_group.setdefault(group_of.get(item_id, item_id), []).append(ok)
    rates = [sum(v) / len(v) for v in by_group.values()]
    return (round(100.0 * sum(rates) / len(rates), 1), len(rates))


def mcnemar_exact(b: int, c: int) -> float:
    """McNemar 精确检验的双侧 p 值。`b` = 只有 A 对，`c` = 只有 B 对。

    用途：base 和 lora 跑的是**同一套 464 道题**，现在却被当成两份独立样本在比。
    配对之后，两边都对、两边都错的题不携带任何信息，真正的证据只在
    「一个对一个错」的那 b + c 道题上 —— 于是问题化简成一次抛硬币检验。

    这也是唯一能回答「L2 退的 14 个点是真回退还是噪声」的算法：
    L2 只有 58 道题，两个独立比例之差的区间会宽到什么都说明不了，
    而配对分析把公共方差消掉了（Miller 2024, arXiv:2411.00640 §4；
    Bowyer 2025 也把配对设定单列一节，并指出配对区间更窄）。

    实现是精确二项检验（p=0.5），不是卡方近似 —— b+c 常常只有个位数，
    卡方近似在那里不成立。零依赖：`math.comb` 就够。
    """
    n = b + c
    if n == 0:
        # 两个模型在每一道题上表现完全一致：没有任何证据说它们不同。
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, round(2 * tail, 4))
