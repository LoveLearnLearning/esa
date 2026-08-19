# backend/scripts/dataset/generators/gen_new_tools.py

"""6 个新增工具的数据生成器。

get_mastery_level / get_weak_prerequisites / get_review_timing /
record_learning_evidence / get_learning_evidence_summary / search_core_memories

这批工具在此前的数据里是完全空白。生成重点是**混淆对**：每个正例都配一个词面
相似但正确答案是别的工具（或不调用）的对照，否则模型只会学到"看见学情词就调工具"。

用法：
    python3 dataset/generators/gen_new_tools.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa.ir import Sample, ToolCall, ToolResult, Turn, dump_samples, load_schemas  # noqa: E402
from esa.render import pick_tool_names  # noqa: E402
from esa.system_prompt import system_for  # noqa: E402
from esa.tools_exec import execute  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / "dataset/seeds/new_tools.yaml"
SCHEMAS = ROOT / "dataset/schemas/tool_schemas.json"
OUT = ROOT / "dataset/data/ir/new_tools.jsonl"
SOURCE = "gen_new_tools.py"

SYSTEM = (
    "你是 ESA 学习辅助 Agent，帮助计算机专业学生规划学习。"
    "需要用户学情数据时调用相应工具；required 参数缺失时不要猜测，应向用户询问；"
    "只有确实需要时才调用工具，不要为了调用而调用。"
)

# 每个正例组该调哪个工具；混淆组该调哪个（None = 不调用任何工具）
POSITIVE_TOOL = {
    "get_mastery_level": "get_mastery_level",
    "get_weak_prerequisites": "get_weak_prerequisites",
    "get_review_timing": "get_review_timing",
    "get_learning_evidence_summary": "get_learning_evidence_summary",
    "search_core_memories": "search_core_memories",
}
CONFUSION_TARGET = {
    "混淆_应调get_mastery_report": "get_mastery_report",
    "混淆_应调recommend_practice": "recommend_practice",
    "混淆_应调get_mastery_level": "get_mastery_level",
    "混淆_应调record_answer": "record_answer",
    "混淆_应调get_core_memories": "get_core_memories",
}

# record_learning_evidence 各正例组对应的活动类型与附加参数。
# 这些参数不能乱填 —— schema 明确写了 self_confidence「学生没有提供时不要猜测、不要传」，
# error_type「只有确有错误证据时填写」。所以只在话术里真的出现了对应信息时才带上。
EVIDENCE_GROUPS = {
    "正例_teach_back": {"activity_type": "teach_back", "explanation_score": 0.7, "independent": True},
    "正例_hint": {"activity_type": "hint", "hint_level": 3, "correct": True, "independent": False},
    "正例_transfer": {"activity_type": "transfer", "transfer_score": 0.4, "correct": False},
    "正例_带自评信心": {"activity_type": "practice", "correct": True, "self_confidence": 0.5},
    "正例_带错误类型": {"activity_type": "practice", "correct": False, "error_type": "conceptual",
                  "misconception": "把最坏情况当成平均情况"},
}


# record_learning_evidence 有 5 个正例组，若每组都给 48 条就会占掉一半篇幅。
# 按"每个工具总量大致相当"来分配。
BUDGETS = {"record_learning_evidence": 20}


def flat_kps(cfg) -> list[tuple[str, str]]:
    """处理 `flat_kps` 相关逻辑。"""
    return [(course, kp) for course, kps in cfg["kp_pool"].items() for kp in kps]


def mk(sid, tpl, category, system, tools, turns, version, rng, all_names, topic=""):
    """处理 `mk` 相关逻辑。

    Args:
        sid: object => `sid` 参数。
        tpl: object => `tpl` 参数。
        category: object => `category` 参数。
        system: object => `system` 参数。
        tools: object => 可用工具列表。
        turns: object => `turns` 参数。
        version: object => `version` 参数。
        rng: object => `rng` 参数。
        all_names: object => `all_names` 参数。
        topic: object => `topic` 参数。

    Returns:
        object => 处理结果。
    """
    return Sample(
        id=sid, template_id=tpl, category=category, schema_version=version,
        system=system_for(turns), tool_names=pick_tool_names(tools, all_names, rng),
        source=SOURCE, topic=topic, turns=turns,
    )


def _answer_for(tool: str, result: dict, kp: str) -> str:
    """最终回答必须引用工具返回的真实数值，否则 validate 的 grounding 检查会拦下。"""
    if tool == "get_mastery_level":
        if not result.get("has_record"):
            return f"你还没有练过「{kp}」，目前没有学习记录。要不要先做一道题建立基线？"
        return (f"你在「{kp}」的掌握度是 **{result['mastery_level']}**（{result['status']}），"
                f"已练习 {result['practice_count']} 次，当前记忆保持率 {result['retention']}。")
    if tool == "get_weak_prerequisites":
        items = result["weak_prerequisites"]
        if not items:
            return f"「{kp}」的前置知识点你掌握得都还可以，可以直接开始练这个点。"
        names = "、".join(f"{i['name']}（{i['mastery_level']}）" for i in items[:3])
        return (f"「{kp}」有 {result['count']} 个前置比较薄弱：{names}。"
                f"建议先补最靠底层的「{items[-1]['name']}」，再回头练「{kp}」会顺很多。")
    if tool == "get_review_timing":
        if not result.get("has_record"):
            return f"「{kp}」还没有练习记录，无法预测复习时间。"
        if result["needs_review"]:
            return (f"「{kp}」当前回忆概率已经降到 **{result['current_retention']}**，"
                    f"低于阈值，建议现在就复习一遍。")
        return (f"「{kp}」当前回忆概率 **{result['current_retention']}**，还比较稳固。"
                f"建议 {result['days_until_review']} 天后复习，也就是 {result['recommended_date']}。")
    if tool == "get_learning_evidence_summary":
        if result["evidence_count"] == 0:
            return "最近还没有积累到学习过程证据，多做几次练习后我再帮你诊断。"
        errs = "、".join(f"{k}×{v}" for k, v in result["error_type_counts"].items()) or "暂无明显集中的错误类型"
        return (f"最近 {result['evidence_count']} 条学习证据显示：独立完成率 **{result['independent_rate']}**，"
                f"平均提示等级 {result['avg_hint_level']}，正确率 {result['correct_rate']}。"
                f"错误类型分布：{errs}。")
    if tool == "search_core_memories":
        if result["count"] == 0:
            return "我这边没有检索到相关的长期记忆。"
        m = result["memories"][0]
        return f"我记得你的「{m['memory_key']}」：{m['content']}。我按这个来。"
    if tool == "record_learning_evidence":
        st = result["state"]
        return (f"记下了。「{st['kp_id']}」的掌握度更新为 **{st['mastery_level']}**，"
                f"累计练习 {st['practice_count']} 次。")
    if tool == "get_mastery_report":
        scope = result["course"] or "全部课程"
        w = result["weak_points"][:2]
        names = "、".join(f"{x['kp_id']}（{x['mastery_level']}）" for x in w)
        return (f"你在**{scope}**共 {result['total_points']} 个知识点，平均掌握度 "
                f"**{result['avg_mastery']}**。最薄弱的是：{names}。")
    if tool == "recommend_practice":
        r0 = result["recommendations"][0]
        return (f"建议优先练「{r0['name']}」，掌握度 {r0['mastery_level']}，"
                f"优先级 {r0['priority']}——{'；'.join(r0['reasons'])}。")
    if tool == "get_core_memories":
        ms = result["memories"]
        items = "；".join(f"{m['memory_key']}：{m['content']}" for m in ms[:3])
        return f"我一共保存了 {result['count']} 条关于你的核心记忆，包括：{items}。"
    if tool == "record_answer":
        # 答对和答错要给不同的回应 —— 用同一句话打发，等于告诉模型对错无所谓。
        head = "记下了。" if result["correct"] else "记下了，这次没做对。"
        tail = ("" if result["correct"]
                else f"要不要我帮你看看「{result['kp_id']}」是卡在哪一步？")
        return (f"{head}「{result['kp_id']}」的掌握度从 {result['mastery_before']} "
                f"更新到 **{result['mastery_after']}**，累计练习 {result['practice_count']} 次。{tail}")
    return "好的。"


def gen_positive(cfg, tool, group, phrasings, rng, all_names, version, out, budget):
    """处理 `gen_positive` 相关逻辑。

    Args:
        cfg: object => `cfg` 参数。
        tool: object => `tool` 参数。
        group: object => `group` 参数。
        phrasings: object => `phrasings` 参数。
        rng: object => `rng` 参数。
        all_names: object => `all_names` 参数。
        version: object => `version` 参数。
        out: object => `out` 参数。
        budget: object => `budget` 参数。
    """
    kps = flat_kps(cfg)
    rng.shuffle(kps)

    # 只有话术里真的带 {kp} 时，遍历知识点才能产出不同的问句；
    # 否则每个知识点都会渲染出同一句话。前面已经因此混进过两批字面重复，
    # 这次是 check_exact_duplicates 自动抓出来的。
    # 不带占位符的话术只出一条，凑不满预算就如实报缺，不复制粘贴。
    pairs: list[tuple[str, str]] = []
    for p in phrasings:
        if "{kp}" in p:
            pairs += [(kp, p) for _, kp in kps]
        else:
            pairs.append((rng.choice(kps)[1], p))

    n = 0
    for kp, p in pairs:
        if n >= budget:
            break
        query = p.format(kp=kp, kp2="链表")
        has_kp = "{kp}" in p
        if tool == "record_learning_evidence":
            args = {"kp_id": kp, **EVIDENCE_GROUPS[group]}
        elif tool == "get_learning_evidence_summary":
            args = {"kp_id": kp} if has_kp else {}
        elif tool == "search_core_memories":
            args = {"query": kp if has_kp else "学习目标"}
        else:
            args = {"kp_id": kp}
        try:
            result = execute(tool, args)
        except Exception as exc:  # noqa: BLE001
            print(f"    ⚠️  {tool}({args}) 执行失败，已跳过：{exc}")
            continue
        out.append(mk(
            f"{tool}_{group}_{n:04d}", f"{tool}__{group}__{kp if has_kp else group}",
            "single_tool_call", SYSTEM, [tool],
            [Turn(role="user", content=query),
             Turn(role="tool_call", calls=[ToolCall(tool, args)]),
             Turn(role="tool_result", results=[ToolResult(tool, result)]),
             Turn(role="assistant", content=_answer_for(tool, result, kp))],
            version, rng, all_names, topic=kp))
        n += 1
    if n < budget:
        print(f"    {tool}/{group}: {n}/{budget}，需补话术种子")


# 各工具的最小合法参数。缺了必填参数会抛 TypeError，
# 而之前那个 `except Exception: continue` 会把整批样本静默吞掉 ——
# record_answer 的混淆样本就是这么一条都没生成的，直到覆盖率报告显示 0 才发现。
# 第三个参数 meta 是种子里显式给出的语义标签（目前只有 record_answer 的 correct 用到）。
#
# ⚠️ `record_answer` 原来写死 `"correct": True`，不管用户说的是做对了还是答错了 ——
# 「刚做完哈希表的练习，答错了」的 gold 也成了 correct=True，等于教模型把错的记成对的。
# 凡是**语义标签**，一律从种子里读，不在生成器里猜：生成器能程序化决定的是参数怎么填，
# 不是用户到底答对没答对。
CONFUSION_ARGS = {
    "recommend_practice": lambda course, kp, meta: {"course": course, "weeks_to_exam": 4},
    "get_mastery_report": lambda course, kp, meta: {"course": course},
    "get_core_memories": lambda course, kp, meta: {},
    "record_answer": lambda course, kp, meta: {"kp_id": kp, "correct": meta["correct"]},
    "get_mastery_level": lambda course, kp, meta: {"kp_id": kp},
}


def _seed_text_meta(item) -> tuple[str, dict]:
    """种子既可以是纯字符串，也可以是 {q: ..., 其它语义标签}。"""
    if isinstance(item, dict):
        return item["q"], item
    return item, {}


def gen_confusion(cfg, wrong_tool, group, phrasings, right_tool, rng, all_names, version, out):
    """混淆样本：诱饵工具必须在 tool_names 里，否则模型没机会学会区分。"""
    kps = flat_kps(cfg)
    for j, item in enumerate(phrasings):
        p, meta = _seed_text_meta(item)
        course, kp = kps[j % len(kps)]
        query = p.format(kp=kp, kp2="链表")
        args = CONFUSION_ARGS[right_tool](course, kp, meta)
        try:
            result = execute(right_tool, args)
        except Exception as exc:  # noqa: BLE001
            # 不静默跳过：吞掉异常等于让整批样本凭空消失
            print(f"    ⚠️  {group} → {right_tool}({args}) 执行失败，已跳过：{exc}")
            continue
        answer = _answer_for(right_tool, result, kp)
        out.append(mk(
            f"{wrong_tool}_conf_{j:03d}", f"{wrong_tool}__{group}__{j:03d}",
            "single_tool_call", SYSTEM,
            [right_tool, wrong_tool],  # 诱饵与正解同时在场
            [Turn(role="user", content=query),
             Turn(role="tool_call", calls=[ToolCall(right_tool, args)]),
             Turn(role="tool_result", results=[ToolResult(right_tool, result)]),
             Turn(role="assistant", content=answer)],
            version, rng, all_names, topic=kp))


def gen_gate_negative(cfg, tool, group, phrasings, rng, all_names, version, out, reply):
    """gate 未满足 → 完全不调用工具。诱饵工具必须在场。"""
    kps = flat_kps(cfg)
    for j, p in enumerate(phrasings):
        course, kp = kps[j % len(kps)]
        query = p.format(kp=kp, kp2="链表")
        out.append(mk(
            f"{tool}_gate_{j:03d}", f"{tool}__{group}__{j:03d}",
            "hard_negative", SYSTEM,
            [tool, "record_answer", "get_mastery_level"],
            [Turn(role="user", content=query),
             Turn(role="assistant", content=reply.format(kp=kp))],
            version, rng, all_names, topic=kp))


GATE_REPLIES = {
    "record_learning_evidence": (
        "好，等你做完再告诉我结果，我再记录。现在还没有实际作答，我不会凭空写学习记录。"
        "要不要我先出一道「{kp}」的题？"
    ),
    "search_core_memories": None,  # 逐条另写，见下
}

ROUTINE_REPLIES = [
    "「{kp}」我直接讲就行，不用去翻你的长期记忆。",
    "这个问题不依赖你之前保存的信息，我直接回答。",
    "不用查记忆，我直接说。",
]


def main() -> int:
    """运行当前模块的命令行入口。"""
    rng = random.Random(20260810)
    cfg = yaml.safe_load(SEEDS.read_text(encoding="utf-8"))
    schemas, version = load_schemas(SCHEMAS)
    all_names = [s["function"]["name"] for s in schemas]
    out: list[Sample] = []

    for tool, groups in cfg.items():
        if tool == "kp_pool":
            continue
        for group, phrasings in groups.items():
            if group.startswith("正例"):
                target = POSITIVE_TOOL.get(tool, tool)
                gen_positive(cfg, target, group, phrasings, rng, all_names, version, out,
                             budget=BUDGETS.get(tool, 48))
            elif group.startswith("混淆"):
                gen_confusion(cfg, tool, group, phrasings, CONFUSION_TARGET[group],
                              rng, all_names, version, out)
            elif group.startswith("gate未满足"):
                if tool == "search_core_memories":
                    for j, p in enumerate(phrasings):
                        kp = flat_kps(cfg)[j % len(flat_kps(cfg))][1]
                        out.append(mk(
                            f"{tool}_gate_{j:03d}", f"{tool}__{group}__{j:03d}",
                            "hard_negative", SYSTEM, [tool, "get_core_memories"],
                            [Turn(role="user", content=p.format(kp=kp, kp2="链表")),
                             Turn(role="assistant", content=rng.choice(ROUTINE_REPLIES).format(kp=kp))],
                            version, rng, all_names, topic=kp))
                else:
                    gen_gate_negative(cfg, tool, group, phrasings, rng, all_names,
                                      version, out, GATE_REPLIES[tool])

    dump_samples(out, OUT)
    from collections import Counter

    print(f"生成 {len(out)} 条 → {OUT.relative_to(ROOT)}")
    for cat, n in sorted(Counter(s.category for s in out).items()):
        print(f"  {cat:20s} {n}")
    print("\n按工具：")
    calls = Counter(c.name for s in out for t in s.turns for c in t.calls)
    for t, n in calls.most_common():
        print(f"  {t:32s} {n}")
    print(f"  {'(不调用)':32s} {sum(1 for s in out if not s.called_tool_names())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
