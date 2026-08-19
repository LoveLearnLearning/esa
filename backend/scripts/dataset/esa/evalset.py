# backend/scripts/dataset/esa/evalset.py

"""评测集构建：按行为类别显式挑选，不靠随机切分。

为什么不用 split.py 的随机分层：
  tool_error 只有 8 条、clarify 的 template 组也少，随机切分下它们要么整组进 train、
  要么在 val/test 里一条不剩 —— 前面已经反复出现"test 里没有 clarify 类样本"的告警。
  评测集本来就该按"要考什么行为"来挑，而不是碰运气。

三层设计（对应交接文档 7.x）：
  L1 同分布   每个 State 留出部分事实组合         → 规律学会了没有
  L2 状态外推 整组留出某些 template               → 规律能否泛化到没见过的组合
  L3 场景外推 留出整个场景/工具                   → 能否泛化到新任务

**评测集绝不能进训练集**：build() 会同时产出 eval 和 train，并断言两者的
template_id 不相交。这是防泄题的唯一保障。

用法：
    PYTHONPATH=dataset python3 -m esa.evalset --out dataset/data/eval
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

from .ir import (
    ROLE_ASSISTANT,
    ROLE_TOOL_CALL,
    ROLE_TOOL_RESULT,
    ROLE_USER,
    Sample,
    iter_ir_files,
    load_samples,
    load_schemas,
    schemas_by_name,
)
from .paths import in_dataset
from .render import to_sharegpt
from . import review

# 每个类别至少要有多少条进评测集。低于这个数，该行为的指标就没有统计意义。
QUOTA = {
    "single_tool_call": 90,
    "clarify": 30,
    "hard_negative": 40,
    "multi_turn_tool": 20,
    "tool_error": 12,
    # refusal 全库只有 19 条，配额给 6 —— 既让这个行为在评测里有统计意义，
    # 又给训练集留下大部分。数据补多了再往上调。
    "refusal": 6,
}

# 返回值是「要照做的流程」而不是「要引用的数据」的工具。
# system prompt 明确要求 load_skill 之后「按正文执行」，复述正文反而是错的，
# 所以对它们出不了 RESPOND_TOOL_RESULT 那道题（忠实度检查不成立）。
# 这份名单必须和 validate.py 的 GROUNDING_EXEMPT 保持一致。
GROUNDING_EXEMPT = {"load_skill"}

# L3 场景外推：这些 template 前缀整体留出，训练时完全不给。
# 选 get_review_timing 是因为它有独立的正例组，且与 get_mastery_level 构成混淆对
# —— 正好能测"模型有没有真正理解两者区别"，而不是背下了见过的问法。
L3_HOLDOUT_PREFIXES = ("get_review_timing__",)

# 补充评测集：这些 template **既不进训练集，也不进主评测集**，单独出一份
# `eval_supp.jsonl`。约定见 `generators/gen_supplement.py`（改一边必须改两边）。
#
# 为什么必须在建 pool **之前**摘出去，而不是在后面过滤
# --------------------------------------------------
# 下面挑评测模板的方式是「按类别配额 + rng.shuffle(pool)」，而
# `random.shuffle` 消耗的随机数与 `len(pool)` 成正比 —— **任何一个类别多几个
# 模板，后面所有类别抽到的模板都会跟着变**。那 464 道题的题面就不是原来那套了，
# 而「这张表只能和作业 77999 那版基线比」是对外表述的硬约束
# （超算手册三之七）。摘在最前面，主评测集才逐字节不变。
#
# 补充集为什么不能并进主表：它是**另一把尺子**（不同题目、不同分母）。
# 它要回答的是「拒绝 6 道、追问 4 个模板」这种分母下测不出来的东西，
# 单独一张表报，不拿它讲「微调带来了多少提升」。
SUPPLEMENT_PREFIXES = ("supp__",)


def is_supplement(template_id: str) -> bool:
    """这个 template 属于补充评测集吗。"""
    return template_id.startswith(SUPPLEMENT_PREFIXES)


def expected_action(s: Sample) -> str:
    """从样本反推**第一道题**的标准动作，作为评测的 gold label。

    与设计总表 00 页的决策树同一套词表。

    ⚠️ 一条样本可以出**两道题**，这个函数只管第一道：
      第一道 = 模型第一次该出手时做什么（本函数）
      第二道 = 工具成功返回之后该怎么说（`RESPOND_TOOL_RESULT`，见 respond_cut_point）
    """
    if not s.called_tool_names():
        if s.category == "clarify":
            return "ASK_USER"
        # `refusal` 和 `hard_negative` 都是"不该调工具"，但**不是同一件事**：
        # hard_negative 是"这题不用工具，正常答就行"，refusal 是"这件事不做"。
        # 混成一个 DIRECT_ANSWER 的话，模型照做了也照样满分 —— 而"照做"
        # 正是赛题《02》承诺里明写不能出现的。
        if s.category == "refusal":
            return "REFUSE"
        return "DIRECT_ANSWER"
    if s.category == "tool_error":
        return "RECOVER_TOOL_ERROR"
    return "CALL_TOOL"


def respond_cut_point(s: Sample) -> int | None:
    """「工具成功返回了，接下来该怎么说」这道题的切点；出不了这道题就返回 None。

    为什么必须单独出一道题
    ----------------------
    `cut_point()` 把带工具调用的样本切在**第一次 tool_call**，所以评测只考
    「调不调、调哪个、参数对不对」。工具返回之后模型说的那句话 —— 也就是用户
    真正看到的那句 —— **一次都没有被考过**。

    而「拿到工具结果之后编造内容」恰恰是工具型 Agent 最典型的翻车方式：
    工具返回 44，模型说 46；工具返回空列表，模型编三条推荐出来。
    训练数据里对这一步是有监督的（每条样本的最后一句），评测却完全盲。

    这个洞是对照架构 V1 的 Expected Behavior 受控词表时发现的：
    他们冻结了 6 个动作，我们的 `expected_action()` 只产出 4 个，
    而我们自己的 `enumerate_states.py:125-131` 其实**认得** `RESPOND_TOOL_RESULT`
    并会把它当成 gold 产出 —— 枚举器认得、评测器不认得、数据里一条没标，三方不一致。

    切在哪
    ------
    取**最后一条「成功观测且下一轮就是 assistant」**的位置。取最后一条是因为
    多轮链式调用里，中间那些观测后面跟的是下一次 tool_call，那时的正确动作
    仍然是 CALL_TOOL 而不是 RESPOND_TOOL_RESULT —— 切错地方会把
    「继续调下一个工具」判成「编造结果」。

    以下情况出不了这道题（返回 None）：
      - 没有工具调用（clarify / hard_negative）
      - `tool_error` 类：那是 RECOVER_TOOL_ERROR 的地盘，别串到这里来
      - 观测是失败的
      - `load_skill` 这类返回「要照做的流程」而非「要引用的数据」的工具，
        复述正文反而是错的，忠实度检查对它不成立
    """
    if s.category == "tool_error" or not s.called_tool_names():
        return None
    for i in range(len(s.turns) - 2, -1, -1):
        t, nxt = s.turns[i], s.turns[i + 1]
        if t.role != ROLE_TOOL_RESULT or nxt.role != ROLE_ASSISTANT:
            continue
        if any(r.is_error for r in t.results):
            return None
        if any(r.name in GROUNDING_EXEMPT for r in t.results):
            return None
        return i + 1
    return None


def cut_point(s: Sample) -> int:
    """评测题喂到第几条消息为止（不含这一条）。

    切点就是「模型第一次要产出被考察内容」的位置。三种情况：

    1. **tool_error** —— 切到第一条失败观测之后。这类 State 的前提是工具已经执行并失败，
       要考的是拿到报错之后怎么办。切在用户话之后的话，那一刻的正确行为其实是照常调用工具
       （模型还不知道它会失败），而 gold 写着 RECOVER_TOOL_ERROR，
       判分会把正确行为算成误触发，污染 FPR 这个最重要的指标。

    2. **有工具调用** —— 切在**第一次 tool_call**。
       ⚠️ 这里曾经写成「第一条 tool_call 或 assistant」，于是多轮样本被切在了中间那句应答上：

           [0] user      我想复习计算机组成原理，期末考试还有 1 周。
           [1] assistant 好的。需要我根据这个安排练习计划吗？     ← 错误地切在这里
           [2] user      不好意思打错了，换成操作系统              ← 模型根本看不到
           [3] tool_call recommend_practice(course=操作系统, ...)  ← 却要它预测这个

       24 条多轮题因此变成**无解题**：答案在被截掉的那一轮里。它们还都算在 CALL_TOOL 桶里，
       会以假失败的形式拉低工具准确率和参数匹配率。
       中间那句应答属于**给定上下文**，不是被考察的输出。

    3. **没有工具调用**（追问 / 直接回答）—— 切在第一条 assistant，那就是被考的答案。
    """
    if s.category == "tool_error":
        for i, t in enumerate(s.turns):
            if t.role == ROLE_TOOL_RESULT and any(r.is_error for r in t.results):
                return i + 1

    first_call = next((i for i, t in enumerate(s.turns) if t.role == ROLE_TOOL_CALL), None)
    if first_call is not None:
        return first_call
    return next((i for i, t in enumerate(s.turns) if t.role == ROLE_ASSISTANT), len(s.turns))


def unanswerable(rec: dict) -> str | None:
    """这道评测题是不是无解的？无解就返回原因。

    判据必须精确，不能是「参数值没在前缀里出现」—— 那会误伤一大批**本来就要靠推断**的参数：
    `activity_type='transfer'`（从「我试着用到另一道题上」推）、
    英文检索词（从中文问句翻译）、Skill 名（从任务类型匹配）、
    `operation='summation'`（从数学式子看出来）。这些不在用户话里是正常的，正是要考的能力。

    真正的无解是这一种：**用户明明说了，却被截在给定范围之外。**
    所以判据是「这个取值出现在被截掉的某个用户轮里、而前缀里没有」——
    取值出现在用户话里就证明它是用户给的、不是该推的；被截掉就证明模型看不到。

    比「记得别把切点写错」更根本：切点逻辑以后怎么改，这道断言都拦得住。
    """
    gold = rec["gold"]
    n = gold["n_turns_given"]
    convs = rec["conversations"]
    prefix = " ".join(str(c["value"]) for c in convs[:n])
    cut_user = " ".join(str(c["value"]) for c in convs[n:] if c["from"] == "human")
    if not cut_user:
        return None
    for args in gold["expected_arguments"]:
        for key, val in args.items():
            if isinstance(val, bool) or val in (None, ""):
                continue
            text = str(val)
            if text not in prefix and text in cut_user:
                return (f"参数 {key}={val!r} 只出现在被截掉的用户轮里 —— "
                        f"模型看不到，却要它答对（只喂了前 {n} 轮）")
    return None


def assert_answerable(records: list[dict]) -> None:
    """评测集里不允许存在无解题。有就让构建失败，别让它悄悄进指标。"""
    bad = [(r["gold"]["id"], why) for r in records if (why := unanswerable(r))]
    if bad:
        lines = "\n".join(f"  {i}: {w}" for i, w in bad[:10])
        raise AssertionError(
            f"{len(bad)} 道评测题无解（答案在被截掉的轮次里）：\n{lines}\n"
            f"多半是 cut_point 切早了。"
        )


def assert_no_train_overlap(records: list[dict], train_set: list[Sample]) -> None:
    """评测题的**最后一句用户话**不得在训练集里出现过。

    `template_id` 整组切分只能保证「同一个模板不跨集合」，拦不住**字面泄漏**：
    改口话术「等等，不是 8 周，是 3 周后就考」只带周数不带课程，
    不同课程的样本会渲染出完全相同的句子，于是 template_id 不相交、原句却一模一样。
    模型见过这句话、也见过它该配什么参数，评测就不再是「没做过的卷子」。

    但**光重复不算泄漏**，还得那句话真的携带答案。
    「那现在该练什么？」这类追问是故意不带信息的（`参数在历史轮` 这个状态的意义就在于
    考「别重复追问、去上一轮取参数」），句子必然反复出现，而答案全在更早的轮次里，
    模型从这句话本身占不到任何便宜。所以判据加一条：**这句话里得含有 gold 参数的取值**。
    """
    def last_user(convs) -> str | None:
        """处理 `last_user` 相关逻辑。"""
        us = [c["value"] for c in convs if c["from"] == "human"]
        return us[-1] if us else None

    seen = {t.content for s in train_set for t in s.turns
            if t.role == ROLE_USER and t.content}
    dup = []
    for r in records:
        line = last_user(r["conversations"])
        if line not in seen:
            continue
        carries = any(str(v) in line
                      for args in r["gold"]["expected_arguments"]
                      for v in args.values()
                      if not isinstance(v, bool) and v not in (None, ""))
        if carries:
            dup.append(r["gold"]["id"])
    if dup:
        raise AssertionError(
            f"{len(dup)} 条评测题的最后一句用户话在训练集里出现过（字面泄漏）：{dup[:8]}\n"
            f"去 seeds 里把这类话术补得更独特，让它随事实组合唯一。"
        )


def gold_of(s: Sample, layer: str | None = None) -> dict:
    """一条评测题的标准答案。

    `layer` 必须写进来。它原先只是 build() 里的一个局部变量，用于打印统计，
    没落到每条记录上 —— 于是判分时根本没法按层分开报，
    「已学能力」和「未见工具泛化」混在一个总分里。
    """
    n = cut_point(s)
    # 标准答案只包含切点**之后**该发生的调用。
    # 「如实说明不重试」的样本这里是空的；「改参数重试」的样本是那一次修正后的调用。
    calls = [c for t in s.turns[n:] for c in t.calls]
    return {
        "id": s.id,
        "category": s.category,
        "template_id": s.template_id,
        "expected_action": expected_action(s),
        "expected_tools": [c.name for c in calls],
        "expected_arguments": [c.arguments for c in calls],
        "n_turns_given": n,
        "layer": layer,
    }


def build(
    samples: list[Sample],
    seed: int = 20260810,
) -> tuple[list[Sample], list[Sample], dict, list[Sample]]:
    """返回 (评测集, 训练集, 统计, 补充评测集)。三者的 template_id 互不相交。"""
    rng = random.Random(seed)

    # ⚠️ 补充集必须在**这里**摘掉 —— 早于 by_tpl，也就早于下面的 rng.shuffle。
    # 理由见 SUPPLEMENT_PREFIXES 的注释：shuffle 消耗的随机数与 pool 长度成正比，
    # 晚一步摘就会把主评测集的抽样整个重排。
    supp_set = sorted((s for s in samples if is_supplement(s.template_id)),
                      key=lambda x: (x.template_id, x.id))
    main_samples = [s for s in samples if not is_supplement(s.template_id)]

    by_tpl: dict[str, list[Sample]] = defaultdict(list)
    for s in main_samples:
        by_tpl[s.template_id].append(s)

    eval_tpls: set[str] = set()
    layer: dict[str, str] = {}

    # ---- L3：整组留出 ----
    for tpl in by_tpl:
        if tpl.startswith(L3_HOLDOUT_PREFIXES):
            eval_tpls.add(tpl)
            layer[tpl] = "L3_场景外推"

    # ---- L1 / L2：按类别配额挑 template ----
    tpls_by_cat: dict[str, list[str]] = defaultdict(list)
    for tpl, items in by_tpl.items():
        if tpl not in eval_tpls:
            tpls_by_cat[items[0].category].append(tpl)

    for cat, want in QUOTA.items():
        pool = sorted(tpls_by_cat.get(cat, []))
        rng.shuffle(pool)
        taken = 0
        for i, tpl in enumerate(pool):
            if taken >= want:
                break
            # 该类别只剩最后一个 template 时不能全拿走，否则训练集里这个行为归零
            if len(pool) - i <= 1:
                break
            eval_tpls.add(tpl)
            # 大组（同一事实组合的多种问法）算 L1，小组算 L2
            layer[tpl] = "L1_同分布" if len(by_tpl[tpl]) >= 3 else "L2_状态外推"
            taken += len(by_tpl[tpl])

    # ⚠️ 必须 sorted()。`eval_tpls` 是 set，跨进程迭代顺序受 PYTHONHASHSEED 影响，
    # 直接迭代会让 eval.jsonl 的**行序**每次都不一样 —— 内容一模一样，字节却对不上。
    #
    # 实测过：连跑三次，441 道题、id 集合完全相同，三个 sha256 却互不相同。
    # 后果不是"数据错了"，而是**没法用 diff 回答"评测集到底有没有变"**：
    # 每次重跑都产生一大片假差异，真的改动就淹在里面了。
    # 而"评测集必须冻结、改动要看得见"正是它防泄题之外的第二个职责。
    # 赛题《03—技术方案说明》也明确要求可复现。
    eval_set = [s for tpl in sorted(eval_tpls) for s in by_tpl[tpl]]
    train_pool = [s for tpl in sorted(by_tpl) if tpl not in eval_tpls for s in by_tpl[tpl]]

    # ---- 未经人工复核的样本不进训练集（组长 2026-08-11 明确要求）----
    #
    # 这些是写作类内容（概念讲解、hard_negative 的讲解正文），机器验不了正文是否属实。
    # 宁可比例难看也不拿可疑数据训练 —— 训练集里的每一句话都会被模型当成事实学走。
    #
    # 只挡训练，**不挡评测**：评测判的是「该不该调工具、调哪个、参数对不对」，
    # 这些标签是机器可判的，正文没核验不影响它们的有效性。
    # 清单见 dataset/docs/待人工复核.md。审完**逐条**登记进 seeds/reviewed.yaml
    # （要签名字），这一条就自动回到训练集 —— 不必也不该去改生成器里那个按组写死的
    # needs_review，那样会把同组没审的一起放行。
    # 存在性检查要对**整个语料**做：待复核样本有一部分落在评测集里，
    # 只拿 train_pool 去查会把"审完的那条正好在评测集"误报成"这个 id 不存在"。
    # 存在性检查对**整个语料**做（含补充集）—— 只拿一部分去查会把
    # 「审完的那条正好在另一部分」误报成「这个 id 不存在」。
    review.assert_no_stale(samples)
    held = review.pending(train_pool)
    held_ids = {s.id for s in held}
    train_set = [s for s in train_pool if s.id not in held_ids]

    # 防泄题：三份的 template_id 必须两两不相交
    overlap = {s.template_id for s in eval_set} & {s.template_id for s in train_set}
    assert not overlap, f"评测集与训练集共享 template_id，存在泄题：{sorted(overlap)[:5]}"
    supp_tpls = {s.template_id for s in supp_set}
    bad = supp_tpls & ({s.template_id for s in eval_set} | {s.template_id for s in train_set})
    assert not bad, f"补充集的 template 漏进了主评测集或训练集：{sorted(bad)[:5]}"

    def no_call_ratio(items: list[Sample]) -> float:
        """「不调用类」占比 —— 整条样本一次工具都没调。

        这是防「见什么都调工具」的唯一配平指标，上一轮花大力气从 5.9% 修上来的，
        所以每次改动都要把它算出来看一眼，不能等训完 demo 翻车才发现。
        """
        if not items:
            return 0.0
        return sum(1 for s in items if not s.called_tool_names()) / len(items)

    n_respond = sum(1 for s in eval_set if respond_cut_point(s) is not None)

    stats = {
        "eval_total": len(eval_set),
        # 评测**题**数 = 样本数 + 能出第二道题的样本数。
        # 这两个数不一样，报告里要分开说，否则「261 条」到底指题还是样本会含混。
        "eval_questions": len(eval_set) + n_respond,
        "respond_questions": n_respond,
        "train_total": len(train_set),
        "train_held_for_review": len(held),
        "train_held_by_category": dict(Counter(s.category for s in held)),
        "no_call_ratio_before_hold": round(no_call_ratio(train_pool), 4),
        "no_call_ratio": round(no_call_ratio(train_set), 4),
        "eval_by_category": dict(Counter(s.category for s in eval_set)),
        "eval_by_layer": dict(Counter(layer[s.template_id] for s in eval_set)),
        # 按**题**统计，不是按样本 —— 一条样本可能出两道题，
        # 按样本统计会让 RESPOND_TOOL_RESULT 整类在报告里消失。
        "eval_by_action": dict(Counter(
            [expected_action(s) for s in eval_set]
            + ["RESPOND_TOOL_RESULT"] * n_respond
        )),
        # 判分要按层分开报，所以这张映射必须带出去
        "layer_by_template": {s.template_id: layer[s.template_id] for s in eval_set},
        # 补充集：一条一个模板，所以模板数应当等于条数。
        # 这个等式是它存在的理由 —— 一旦小于条数，说明有人往里加改写了，
        # 而补改写只会让簇更大，一点也不会让指标更可信。
        "supp_total": len(supp_set),
        "supp_templates": len(supp_tpls),
        "supp_by_category": dict(Counter(s.category for s in supp_set)),
        "supp_by_action": dict(Counter(expected_action(s) for s in supp_set)),
    }
    return eval_set, train_set, stats, supp_set


# 补充集在分层里的标签。它不是 L1/L2/L3 中的任何一层 ——
# 那三层是按「与训练分布的距离」分的，而补充集整体不进训练集，
# 混进任何一层都会让那一层的含义变味。
SUPP_LAYER = "SUPP_补充集"


def to_questions(samples, by_name, layer: dict[str, str],
                 fixed_layer: str | None = None) -> list[dict]:
    """把样本渲染成评测题。一条样本可能出两道题。

    抽出来是为了让主评测集和补充集**走同一条渲染路径** ——
    两边各写一份迟早会分叉，而分叉的后果是「主表能判的题补充表判不了」。
    """
    records: list[dict] = []
    for s in samples:
        lay = fixed_layer or layer.get(s.template_id)
        rec = to_sharegpt(s, by_name)
        rec["gold"] = gold_of(s, lay)
        records.append(rec)

        # 第二道题：工具成功返回之后该怎么说。
        # 同一条样本出两道题，考的是两件不同的事，所以 id 加后缀区分。
        n = respond_cut_point(s)
        if n is not None:
            rec2 = to_sharegpt(s, by_name)
            rec2["gold"] = {
                "id": f"{s.id}#respond",
                "category": s.category,
                "template_id": s.template_id,
                "expected_action": "RESPOND_TOOL_RESULT",
                # 观测已经拿到，后面不该再有调用。空列表让 score() 走 want_call=False，
                # 但**必须**在 score() 里单独分流，绝不能落进 FPR 的分母 ——
                # 5.11 就是 RECOVER_TOOL_ERROR 掉进 FPR 分母那次。
                "expected_tools": [],
                "expected_arguments": [],
                "n_turns_given": n,
                "layer": lay,
            }
            records.append(rec2)
    return records


def write(eval_set, train_set, stats, by_name, out_dir: Path,
          supp_set=()) -> None:
    """写入评测集、补充评测集与训练集 IR。

    Args:
        eval_set: object => 主评测集样本。
        train_set: object => 训练集样本。
        stats: object => `build()` 的统计。
        by_name: object => 工具 schema，按名字索引。
        out_dir: Path => 落盘目录。
        supp_set: object => 补充评测集样本，单独落 `eval_supp.jsonl`。
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # 评测题：ShareGPT 形式（供渲染 prompt）+ gold（供判分）
    layer = stats.get("layer_by_template", {})
    records = to_questions(eval_set, by_name, layer)

    # 两条断言都在落盘**之前**跑：宁可不产出，也不要产出一份坏评测集。
    assert_answerable(records)
    assert_no_train_overlap(records, train_set)

    with (out_dir / "eval.jsonl").open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 补充评测集：同样的断言、同样的渲染，只是另一个文件。
    supp_records = to_questions(supp_set, by_name, layer, fixed_layer=SUPP_LAYER)
    if supp_records:
        assert_answerable(supp_records)
        assert_no_train_overlap(supp_records, train_set)
        with (out_dir / "eval_supp.jsonl").open("w", encoding="utf-8") as fh:
            for rec in supp_records:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        stats["supp_questions"] = len(supp_records)

    # 训练集的 IR，供 split.py 继续切 train/validation
    with (out_dir / "train_ir.jsonl").open("w", encoding="utf-8") as fh:
        for s in train_set:
            fh.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")

    (out_dir / "eval_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    """运行当前模块的命令行入口。

    Args:
        argv: list[str] | None => `argv` 参数。

    Returns:
        int => 处理结果。
    """
    ap = argparse.ArgumentParser(description="构建评测集（按行为类别显式挑选）")
    ap.add_argument("--ir-dir", default=str(in_dataset("data/ir")))
    ap.add_argument("--schemas", default=str(in_dataset("schemas/tool_schemas.json")))
    ap.add_argument("--out", default=str(in_dataset("data/eval")))
    ap.add_argument("--seed", type=int, default=20260810)
    args = ap.parse_args(argv)

    schemas, _ = load_schemas(args.schemas)
    by_name = schemas_by_name(schemas)
    samples = [s for f in iter_ir_files(args.ir_dir) for s in load_samples(f)]

    eval_set, train_set, stats, supp_set = build(samples, seed=args.seed)
    write(eval_set, train_set, stats, by_name, Path(args.out), supp_set)

    print(f"评测集 {stats['eval_total']} 条样本 → {stats['eval_questions']} 道题"
          f"（其中 {stats['respond_questions']} 道考「工具返回后怎么说」）"
          f" / 训练集 {stats['train_total']} 条  → {args.out}/")

    held_n = stats["train_held_for_review"]
    before, after = stats["no_call_ratio_before_hold"], stats["no_call_ratio"]
    print(f"\n未复核而挡在训练集外：{held_n} 条 "
          f"（{'、'.join(f'{k} {v}' for k, v in sorted(stats['train_held_by_category'].items()))}）")
    print(f"「不调用类」占比：{before:.1%} → {after:.1%}（挡掉之后掉 {before - after:.1%}）")
    if after < 0.15:
        print("  ⚠️  低于 15%：只训正例会让模型见什么都调工具，demo 现场会翻车。")
        print("     补法：审完 docs/待人工复核.md 放回，或补等量负样本。")
    print("\n按类别：")
    for c, n in sorted(stats["eval_by_category"].items()):
        want = QUOTA.get(c, 0)
        mark = "" if n >= want else f"  ← 不足 {want}，该行为的指标统计意义弱"
        print(f"  {c:20s} {n:4d}{mark}")
    print("\n按层：")
    for k, n in sorted(stats["eval_by_layer"].items()):
        print(f"  {k:14s} {n:4d}")
    print("\n按标准动作：")
    for k, n in sorted(stats["eval_by_action"].items()):
        print(f"  {k:22s} {n:4d}")

    if stats.get("supp_total"):
        print(f"\n补充评测集（**不进主表**，单独一份 eval_supp.jsonl）："
              f"{stats['supp_total']} 条 / {stats.get('supp_questions', 0)} 道题 / "
              f"{stats['supp_templates']} 个模板")
        if stats["supp_templates"] != stats["supp_total"]:
            print("  ⚠️  模板数 ≠ 条数：有人往补充集里加了同模板改写。"
                  "补改写只会让簇更大，不会让指标更可信。")
        for k, n in sorted(stats["supp_by_action"].items()):
            print(f"    {k:22s} {n:4d}")

    missing = [c for c in QUOTA if c not in stats["eval_by_category"]]
    if missing:
        print(f"\n⚠️  这些类别在评测集里一条都没有，无法评测：{missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
