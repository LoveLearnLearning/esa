# backend/scripts/dataset/generators/gen_scenarios.py

"""从话术种子库生成学情类场景数据。

覆盖设计总表的 S002 / S003 / S004，对应规律 R001 / R002 / R003 / R004 / R005 / R009。

生成逻辑就是计划里「改动 5」定的那套，替换掉思维导图上的「随机 60 选 40」：
  1. 事实变量笛卡尔积 × 话术种子 = 候选池
  2. 按覆盖度配额采样，不随机丢弃 —— 保证每个变量取值都被覆盖到
  3. 工具返回值一律真实计算（fixtures.py），不编造

用法：
    python3 dataset/generators/gen_scenarios.py
"""

from __future__ import annotations

import itertools
import random
import sys
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa.ir import Sample, ToolCall, ToolResult, Turn, dump_samples, load_schemas  # noqa: E402
from esa.render import pick_tool_names  # noqa: E402
from esa.system_prompt import system_for  # noqa: E402
from esa.tools_exec import execute  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / "dataset/seeds/scenarios.yaml"
SCHEMAS = ROOT / "dataset/schemas/tool_schemas.json"
OUT = ROOT / "dataset/data/ir/scenarios.jsonl"
SOURCE = "gen_scenarios.py"

SYSTEM = (
    "你是 ESA 学习辅助 Agent，帮助计算机专业学生规划学习。"
    "需要用户学情数据时调用相应工具；required 参数缺失时不要猜测，应向用户询问；"
    "参数已在上下文中出现过则不要重复询问。"
)

# 每个 state_key 的目标产出条数。总量对齐计划第三节的配比。
BUDGET = {
    ("S002", "参数齐全"): 150,
    ("S002", "缺weeks"): 90,
    ("S002", "缺course"): 55,
    ("S002", "都缺"): 45,
    ("S002", "参数在历史轮"): 60,
    ("S002", "修改参数"): 40,
    ("S003", "指定课程"): 70,
    ("S003", "不指定课程"): 65,
    # 2026-08-17：从 105 减到 88。移走的 17 条是**疑问句**，它们其实在「查」记忆
    # （「你还记得我…吗」「你那边存了我哪些信息呀」），线上规则允许甚至要求调只读工具，
    # 判成负样本是错的 —— 见交接文档 5.22。它们已挪到 seeds/new_tools.yaml 的
    # search_core_memories 正例 / 混淆_应调get_core_memories。
    # ⚠️ 陈述与感慨仍然留在这里，那才是这一组真正要防的（模型对它们仍会误触发）。
    ("S004", "仅提及未要求"): 88,
}

# 每条样本的用户话术必须互不相同。
#
# 曾经把这里设成 3（允许同一「事实组合 × 话术」重复三次凑数），结果 680 条里有 171 条
# 是字面完全相同的重复 —— 而校验器的近重复检测只比较不同 template_id 之间，抓不到。
# 这正是「样本数 ≠ 有效样本数」的现场。凑不满预算是有用的信号：要么补话术，要么降预算，
# 而不是复制粘贴。
MAX_DUP = 1

# 每个状态实际需要哪些事实变量。
# 不能靠「话术里有没有占位符」来推断 —— 「参数在历史轮」的当前轮话术是
# 「那现在该练什么？」，一个占位符都没有，但工具调用仍然需要 course 和 weeks。
STATE_FACTS = {
    ("S002", "参数齐全"): ["course", "weeks_to_exam"],
    ("S002", "缺weeks"): ["course"],
    ("S002", "缺course"): ["weeks_to_exam"],
    ("S002", "都缺"): [],
    ("S002", "参数在历史轮"): ["course", "weeks_to_exam"],
    ("S002", "修改参数"): ["course", "weeks_to_exam"],
    ("S003", "指定课程"): ["course"],
    ("S003", "不指定课程"): [],
    ("S004", "仅提及未要求"): [],
}


def quota_sample(candidates, key_fns, target, rng):
    """按覆盖度配额采样，替代随机丢弃。

    随机丢弃可能把某个 course 或某个 weeks 取值整个丢掉；配额采样保证
    每个取值至少被覆盖 ⌈target / 取值数⌉ 次，剩余名额再随机补足。
    """
    if target >= len(candidates):
        return list(candidates)

    buckets: dict = defaultdict(list)
    for c in candidates:
        buckets[tuple(f(c) for f in key_fns)].append(c)
    for b in buckets.values():
        rng.shuffle(b)

    chosen, keys = [], sorted(buckets, key=str)
    # 轮转取用，天然保证每个桶被均匀覆盖
    while len(chosen) < target:
        progressed = False
        for k in keys:
            if buckets[k] and len(chosen) < target:
                chosen.append(buckets[k].pop())
                progressed = True
        if not progressed:
            break
    return chosen


# 下面两个函数消费的字段名必须和 fixtures.py 的输出一致，而 fixtures.py 又严格复刻后端。
# 字段名一旦对不上，训练出的模型就会引用线上不存在的字段。
# tests/test_fixture_contract.py 会把这层契约钉住。


def _fmt_plan_answer(result: dict, weeks_to_exam: int) -> str:
    """处理 `_fmt_plan_answer` 相关逻辑。"""
    recs = result["recommendations"][:3]
    lines = [f"根据你在**{result['course']}**的学情，距考试 {weeks_to_exam} 周，建议优先练这几个知识点：\n"]
    for i, r in enumerate(recs, 1):
        why = "；".join(r["reasons"])
        lines.append(f"{i}. **{r['name']}**（掌握度 {r['mastery_level']}，优先级 {r['priority']}）——{why}")
    top = recs[0]
    tail = f"\n先从「{top['name']}」开始，掌握度只有 {top['mastery_level']}，是当前最薄弱的一环。"
    if top["weak_prerequisites"]:
        pre = top["weak_prerequisites"][0]
        tail += f"另外它的前置「{pre['name']}」也才 {pre['mastery_level']}，建议先把这个补上。"
    lines.append(tail)
    return "\n".join(lines)


def _fmt_report_answer(result: dict) -> str:
    """处理 `_fmt_report_answer` 相关逻辑。"""
    scope = result["course"] or "全部课程"
    weak = result["weak_points"][:3]
    weakest = "、".join(f"{x['name'] if 'name' in x else x['kp_id']}（{x['mastery_level']}）" for x in weak)
    lines = [
        f"你在**{scope}**上的学习情况：\n",
        f"- 覆盖知识点 {result['total_points']} 个，平均掌握度 **{result['avg_mastery']}**",
        f"- 最薄弱的三个：{weakest}",
    ]
    stale = result["stale_points"]
    if stale:
        s = stale[0]
        lines.append(f"- 需要复习的有 {len(stale)} 个，记忆保持率最低的是「{s['kp_id']}」，已降到 {s['retention']}")
    w0 = weak[0]
    lines.append(f"\n建议从「{w0['kp_id']}」入手，目前只有 {w0['mastery_level']}，提升空间最大。")
    return "\n".join(lines)


def build(cfg, sid, state_key, rng, all_names, version):
    """为一个 (scenario, state_key) 产出样本列表。"""
    body = cfg[sid]
    facts = body.get("facts", {})
    raw = body["phrasings"][state_key]
    # 「修改参数」按被改字段分组，展平成 (被改字段, 话术) 便于统一处理
    phrasings = (
        [(field, p) for field, lst in raw.items() for p in lst]
        if isinstance(raw, dict)
        else [(None, p) for p in raw]
    )
    target = BUDGET[(sid, state_key)]

    used = STATE_FACTS[(sid, state_key)]
    combos = list(itertools.product(*[facts[k] for k in used])) or [()]

    candidates = [
        {"vals": dict(zip(used, combo)), "phrasing": p, "changes": field, "rep": rep}
        for combo in combos
        for field, p in phrasings
        for rep in range(MAX_DUP)
    ]
    key_fns = [(lambda c, k=k: c["vals"].get(k)) for k in used] + [lambda c: c["phrasing"]]
    picked = quota_sample(candidates, key_fns, target, rng)

    out = []
    for i, c in enumerate(picked):
        s = _render(cfg, sid, state_key, c, i, rng, all_names, version)
        if s is not None:
            out.append(s)
    return out


ALIAS = {"weeks_to_exam": "weeks", "city": "city", "course": "course", "memory_key": "memory_key"}


def _fill(text: str, vals: dict, extra: dict | None = None) -> str:
    """处理 `_fill` 相关逻辑。"""
    kw = {ALIAS[k]: v for k, v in vals.items()}
    kw.update(extra or {})
    return text.format(**kw)


def _old_value(field: str, current, rng):
    """为「修改参数」造一个被覆盖的旧值，必须与新值不同。"""
    pool = {
        "weeks_to_exam": [1, 2, 3, 4, 6, 8, 10, 12, 16],
        "course": ["数据结构", "操作系统", "计算机网络", "计算机组成原理", "数据库原理", "算法设计与分析"],
    }[field]
    choices = [v for v in pool if str(v) != str(current)]
    return rng.choice(choices)


def _render(cfg, sid, state_key, c, idx, rng, all_names, version):
    """渲染 `render` 相关数据。"""
    vals, phrasing = c["vals"], c["phrasing"]
    extra = {}
    if state_key == "修改参数":
        field = c["changes"]
        old = _old_value(field, vals[field], rng)
        extra = {f"old_{ALIAS[field]}": old, "_changed": field, "_old": old}
    query = _fill(phrasing, vals, extra)

    # template_id 的粒度决定切分时什么必须待在一起。
    # 正确的单位是「同一事实组合的所有话术」—— 同一组参数换个问法，工具调用完全相同，
    # 拆到 train/test 两边就是泄漏。而不同事实组合之间是可以分开的（这正是 L1 同分布评测）。
    fact_sig = "_".join(str(vals[k]) for k in sorted(vals)) or "nofacts"
    tpl = f"{sid}__{state_key}__{fact_sig}"
    sample_id = f"{sid.lower()}_{state_key}_{idx:04d}"
    body = cfg[sid]

    def mk(turns, tools, category, ask_for=()):
        """处理 `mk` 相关逻辑。

        Args:
            turns: object => `turns` 参数。
            tools: object => 可用工具列表。
            category: object => `category` 参数。
            ask_for: object => `ask_for` 参数。

        Returns:
            object => 处理结果。
        """
        return Sample(
            id=sample_id, template_id=tpl, category=category, schema_version=version,
            system=system_for(turns), tool_names=pick_tool_names(tools, all_names, rng),
            source=SOURCE, turns=turns, ask_for=list(ask_for),
        )

    # ---- CALL_TOOL：真实执行 ----
    if sid == "S002" and state_key in ("参数齐全", "参数在历史轮", "修改参数"):
        args = {"course": vals["course"], "weeks_to_exam": int(vals["weeks_to_exam"])}
        result = execute("recommend_practice", args)
        answer = _fmt_plan_answer(result, args["weeks_to_exam"])
        call = [
            Turn(role="tool_call", calls=[ToolCall("recommend_practice", args)]),
            Turn(role="tool_result", results=[ToolResult("recommend_practice", result)]),
            Turn(role="assistant", content=answer),
        ]
        if state_key == "参数齐全":
            turns = [Turn(role="user", content=query), *call]
            cat = "single_tool_call"
        else:
            # 多轮：参数在上一轮已给出，本轮不得重复追问
            if state_key == "参数在历史轮":
                lead = f"我在复习{vals['course']}，期末考试在 {vals['weeks_to_exam']} 周后。"
                ack = "好的，记下了。需要我帮你排练习重点的话随时说。"
            else:
                # 修改参数：首轮给的是旧值，本轮被覆盖 —— 工具参数必须用新值
                old_course = extra["_old"] if extra["_changed"] == "course" else vals["course"]
                old_weeks = extra["_old"] if extra["_changed"] == "weeks_to_exam" else vals["weeks_to_exam"]
                lead = f"我想复习{old_course}，期末考试还有 {old_weeks} 周。"
                # ⚠️ 这句原来是**是非问句**「需要我根据这个安排练习计划吗？」，
                # 而本模板里用户的下一句只纠正参数、**从不回答这个问句**。
                # 于是 31 条训练样本在教「用户没确认也直接调工具」，
                # 而误触发率恰恰是我们最重要的指标；评测侧另有 9 道把模型的追问
                # 判成漏调。2026-08-16 基线跑完才看出来（模型的 <think> 明写
                # 「用户只是纠正信息，没有明确要求推荐」—— 它的读法是站得住的）。
                #
                # 数据集内部本来就打架：clarify 类教「模糊就追问」，这里却教「直接调」。
                # 改成陈述句（对齐隔壁 `参数在历史轮` 分支的写法）之后，
                # 用户的纠正就只有一种读法：同一个请求、换个参数 —— 这正是本模板要考的。
                ack = "好的，我这就按这个帮你安排练习计划。"
            turns = [
                Turn(role="user", content=lead),
                Turn(role="assistant", content=ack),
                Turn(role="user", content=query),
                *call,
            ]
            cat = "multi_turn_tool"
        return mk(turns, ["recommend_practice"], cat)

    if sid == "S003":
        args = {"course": vals["course"]} if state_key == "指定课程" else {}
        result = execute("get_mastery_report", args)
        return mk(
            [
                Turn(role="user", content=query),
                Turn(role="tool_call", calls=[ToolCall("get_mastery_report", args)]),
                Turn(role="tool_result", results=[ToolResult("get_mastery_report", result)]),
                Turn(role="assistant", content=_fmt_report_answer(result)),
            ],
            ["get_mastery_report"],
            "single_tool_call",
        )

    # ---- ASK_USER：工具从未被调用，不需要执行 ----
    if state_key.startswith("缺") or state_key == "都缺":
        key = {"缺weeks": "weeks_to_exam", "缺course": "course",
               "都缺": "course_and_weeks", "缺city": "city"}[state_key]
        ask = _fill(rng.choice(body["ask_templates"][key]), vals)
        tool = body["tool"].split(" / ")[0]
        # 该追问哪几个参数是这里唯一知道的地方，必须带进 IR ——
        # 丢掉它，「只询问缺失信息 / 不得重复询问已有信息 / 不得猜测缺失参数」
        # 这三条行为契约就一条都验不了（架构 V1 的 ASK_USER Contract）。
        ask_for = ["course", "weeks_to_exam"] if key == "course_and_weeks" else [key]
        return mk([Turn(role="user", content=query), Turn(role="assistant", content=ask)],
                  [tool], "clarify", ask_for=ask_for)

    # ---- gate 未满足 → DIRECT_ANSWER，不得动记忆 ----
    if sid == "S004" and state_key == "仅提及未要求":
        reply = rng.choice(body["refuse_templates"])
        return mk(
            [Turn(role="user", content=query), Turn(role="assistant", content=reply)],
            ["save_core_memory", "delete_core_memory", "get_core_memories"],
            "hard_negative",
        )

    return None


def main() -> int:
    """运行当前模块的命令行入口。"""
    rng = random.Random(20260809)
    cfg = yaml.safe_load(SEEDS.read_text(encoding="utf-8"))
    schemas, version = load_schemas(SCHEMAS)
    all_names = [s["function"]["name"] for s in schemas]

    samples, shortfalls = [], []
    for (sid, state_key) in BUDGET:
        got = build(cfg, sid, state_key, rng, all_names, version)
        samples += got
        want = BUDGET[(sid, state_key)]
        mark = "" if len(got) >= want else f"  ← 差 {want - len(got)} 条，需补话术种子"
        if len(got) < want:
            shortfalls.append((sid, state_key, len(got), want))
        print(f"  {sid} / {state_key:12s} → {len(got):4d} 条{mark}")

    dump_samples(samples, OUT)
    from collections import Counter

    target = sum(BUDGET.values())
    print(f"\n合计 {len(samples)} / 目标 {target} 条 → {OUT.relative_to(ROOT)}")
    for cat, n in sorted(Counter(s.category for s in samples).items()):
        print(f"  {cat:20s} {n}")

    if shortfalls:
        need = sum(w - g for _, _, g, w in shortfalls)
        print(f"\n还差 {need} 条。这不是要调低预算，是要补话术种子 —— 每条样本的用户话术必须互不相同：")
        for sid, state_key, got, want in shortfalls:
            print(f"  seeds/scenarios.yaml  {sid}.phrasings.{state_key}  需再写 ~{want - got} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
