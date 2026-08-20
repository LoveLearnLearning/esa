# backend/scripts/dataset/generators/gen_negatives.py

"""负样本生成器：工具在场但不该调用。

配比是当前最大的短板 —— "不调用"类只占 5.9%，目标 23%。只训正例会让模型学到
先验 P(调用)≈0.94，见什么都想调工具。

三类：
  meta        元对话（寒暄/致谢/问系统自身）
  gate_*      提到了但没要求 —— 防止不可逆的记忆写入
  traps       概念题撞上工具名

同时产出 save_core_memory / delete_core_memory / propose_core_memory 的**正样本**，
与 gate 负样本构成三方对照：
    本轮明确要求记住/删除   → save / delete
    没要求但带出了稳定信息   → **必须** propose（规则里唯一的强制项）
    只提到短期状态或泛泛自评 → 一个都不调
只有前两种对照的话，模型学到的是"别碰记忆工具"而不是"看用户有没有明确要求"；
少了第三种（2026-08-19 之前 propose 正例是 0 条），模型学不到"推断出来的不能直接 save"。

用法：
    python3 dataset/generators/gen_negatives.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa import fixtures  # noqa: E402
from esa.ir import Sample, ToolCall, ToolResult, Turn, dump_samples, load_schemas  # noqa: E402
from esa.render import pick_tool_names  # noqa: E402
from esa.system_prompt import system_for  # noqa: E402
from esa.tools_exec import execute  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / "dataset/seeds/negatives.yaml"
SCENARIO_SEEDS = ROOT / "dataset/seeds/scenarios.yaml"
SCHEMAS = ROOT / "dataset/schemas/tool_schemas.json"
OUT = ROOT / "dataset/data/ir/negatives.jsonl"
SOURCE = "gen_negatives.py"

SYSTEM = (
    "你是 ESA 学习辅助 Agent，帮助计算机专业学生学习。"
    "只有确实需要时才调用工具，能直接回答的不要调用。"
    "保存或删除长期记忆前，必须确认用户有明确的保存/删除意图。"
)

# ⚠️ 2026-08-19（晚）删掉了 `SAVE_ARGS`。
#
# 它原来是一张按**用户原话**当 key 的写死表，存着 memory_key / content /
# category / known 四项 —— 全是语义标签，正是 5.19 / 5.22 反复讲的
# 「生成器替种子作者做语义决定」。而且改一个字的话术就会查不到、
# 那条样本被静默跳过（只打印一行 ⚠️），5.19 那个「一半话术从没进过数据」
# 就是这么藏了三个月的。
#
# 现在四项全部逐条写在 `seeds/scenarios.yaml` 的 S004.明确要求记住 里，
# 和 `推断出稳定信息`（propose 那组）同一个样式。
# 三条分支的含义仍然重要，注释搬到种子里了。

# 删除是**两步**的：`delete_core_memory` 只认 memory_id，而 id 只能来自
# `get_core_memories` / `search_core_memories` 的返回值（schema 描述里明写）。
# 上一版一步就删，还传了个 memory_key —— 那个参数后端 2026-08-13 就没了。
#
# 为什么用 get_core_memories 而不是 search：这些话术里的词（学习目标 / 回答风格 /
# 薄弱 / 考试安排）大多是抽象词，实测真实检索**搜不到**（见 memory_real.json
# 的 search_matrix）。要拿到 id 就得列全部，这本身就是要教的东西。
DELETE_ARGS = {
    "把我之前设的学习目标删掉吧": "learning_goal",
    "忘掉你记的我的回答风格偏好": "response_style",
    "请删除关于我薄弱知识点的那条记忆。": "weak_topics",
    "我不想让你再记着我的考试安排了，删了它": "exam_schedule",
    "之前存的那个学习目标不作数了，清掉": "learning_goal",
    "帮我把回答风格那条记忆去掉": "response_style",
}

# 按 save 返回的 status 说话。三句话必须不同 —— 用同一句打发，
# 等于告诉模型"存没存成不重要"。
SAVE_REPLIES = {
    "created": "记住了：{content}。之后我会按这个来。",
    "unchanged": "这条我已经记着了，内容和你说的一样（{content}），就不重复存一遍了。",
    "confirmation_required": (
        "这条得你点个头才能改：你之前存的「{key}」是「{old}」，现在要换成「{new}」。\n\n"
        "系统没有直接覆盖，而是挂了一条待确认的修改。你确认一下我就让它生效——"
        "在那之前**旧的那条仍然有效**。"
    ),
}


def mk(sid, tpl, category, tools, turns, version, rng, all_names, topic=""):
    """处理 `mk` 相关逻辑。

    Args:
        sid: object => `sid` 参数。
        tpl: object => `tpl` 参数。
        category: object => `category` 参数。
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
        source=SOURCE, topic=topic or "", turns=turns,
    )


def gen_no_call(group, cfg_group, version, rng, all_names, out):
    """A/B 两类：完全不调用工具。诱饵工具必须在场。"""
    lures = cfg_group["lures"]
    for i, pair in enumerate(cfg_group["pairs"]):
        out.append(mk(
            f"{group}_{i:03d}", f"neg__{group}__{i:03d}", "hard_negative", lures,
            [Turn(role="user", content=pair["q"]),
             Turn(role="assistant", content=pair["a"])],
            version, rng, all_names))


def gen_traps(cfg, version, rng, all_names, out):
    """C 类：概念题撞工具名。topic 挂上后会被 verified_facts 的复杂度核查覆盖。"""
    for i, t in enumerate(cfg["traps"]):
        out.append(mk(
            f"trap_{i:03d}", f"neg__trap__{i:03d}", "hard_negative",
            [t["lure"], "recommend_practice", "get_mastery_level"],
            [Turn(role="user", content=t["q"]),
             Turn(role="assistant", content=t["a"])],
            version, rng, all_names, topic=t.get("topic") or ""))
        out[-1].needs_review = True  # 含事实内容，必须人工过目


def gen_memory_positives(version, rng, all_names, out):
    """save/delete 的正样本 —— 和 gate 负样本构成"明确要求 vs 只是提到"的对照。"""
    cfg = yaml.safe_load(SCENARIO_SEEDS.read_text(encoding="utf-8"))["S004"]["phrasings"]

    for i, item in enumerate(cfg["明确要求记住"]):
        missing = [k for k in ("q", "memory_key", "content", "category") if not item.get(k)]
        if missing:
            raise SystemExit(
                f"seeds/scenarios.yaml 的 S004.明确要求记住 第 {i} 条缺 {missing}：{item!r}\n"
                "这几项是语义标签，必须逐条写在种子里（5.19 / 5.22）。"
            )
        if "known" not in item:
            raise SystemExit(
                f"seeds/scenarios.yaml 的 S004.明确要求记住 第 {i} 条没写 known。\n"
                "它决定走 created / unchanged / confirmation_required 哪一支，"
                "空库就写 `known: []`，别省略 —— 省略和空库不是一回事。"
            )
        q = item["q"]
        args = {"memory_key": item["memory_key"], "content": item["content"],
                "category": item["category"]}
        result = fixtures.save_core_memory(**args, known=fixtures.memory_store(*item["known"]))
        status = result["status"]
        if status == "confirmation_required":
            cand = result["candidate"]
            old = fixtures.memory_store(*item["known"])[cand["memory_key"]]["content"]
            answer = SAVE_REPLIES[status].format(
                key=cand["memory_key"], old=old, new=cand["proposed_content"], content="")
        else:
            answer = SAVE_REPLIES[status].format(content=result["memory"]["content"])
        out.append(mk(
            f"save_pos_{i:03d}", f"mem__save__{status}__{args['memory_key']}__{i:03d}",
            "single_tool_call", ["save_core_memory", "propose_core_memory", "delete_core_memory"],
            [Turn(role="user", content=q),
             Turn(role="tool_call", calls=[ToolCall("save_core_memory", args)]),
             Turn(role="tool_result", results=[ToolResult("save_core_memory", result)]),
             Turn(role="assistant", content=answer)],
            version, rng, all_names))

    for i, q in enumerate(cfg["明确要求删除"]):
        key = DELETE_ARGS.get(q)
        if key is None:
            print(f"    ⚠️  没有为 {q!r} 配置 delete 参数，已跳过")
            continue
        listed = execute("get_core_memories", {})
        target = next((m for m in listed if m["memory_key"] == key), None)
        if target is None:
            print(f"    ⚠️  记忆库里没有 {key!r}，删不了，已跳过")
            continue
        deleted = execute("delete_core_memory", {"memory_id": target["memory_id"]})
        out.append(mk(
            f"del_pos_{i:03d}", f"mem__delete__{key}__{i:03d}",
            # 两次调用 → 不是 single_tool_call。删除**天生是两步**的
            # （先查 id 再删），类别得如实标成多轮工具样本。
            "multi_turn_tool",
            ["delete_core_memory", "get_core_memories", "save_core_memory"],
            [Turn(role="user", content=q),
             # 第一步：拿 id。删除工具只认 memory_id，模型手上没有，必须先查。
             Turn(role="tool_call", calls=[ToolCall("get_core_memories", {})]),
             Turn(role="tool_result", results=[ToolResult("get_core_memories", listed)]),
             # 第二步：拿查到的 id 去删。
             Turn(role="tool_call",
                  calls=[ToolCall("delete_core_memory", {"memory_id": target["memory_id"]})]),
             Turn(role="tool_result", results=[ToolResult("delete_core_memory", deleted)]),
             Turn(role="assistant",
                  content=f"已经删掉「{target['memory_key']}」这条记忆了"
                          f"（内容是「{target['content']}」）。")],
            version, rng, all_names))


# propose 的三句回应按返回值的 candidate_type 分开写。
#
# 后端对**已存在的 key** 产出的是 candidate_type="replace" 并带 expected_revision，
# 对新 key 是 "create"。两支的正确说法不一样：一支是「我记了个待确认的候选」，
# 另一支还得说清「旧的那条还在，没被覆盖」。用同一句话打发，等于教模型
# 把「已挂上待确认」说成「已经存好了」—— 那正是 save 三分支那次修掉的毛病。
PROPOSE_REPLIES = {
    "create": (
        "这条我先记成待确认的候选：「{content}」。\n\n"
        "你确认一下它才会进长期记忆——在那之前我不会把它当成既定事实。"
    ),
    "replace": (
        "你之前存的「{key}」是「{old}」，我按你刚说的挂了一条待确认的修改："
        "「{content}」。\n\n"
        "确认之后才会替换；**在那之前旧的那条仍然有效**。"
    ),
}


def gen_propose_positives(version, rng, all_names, out):
    """`推断出稳定信息` → propose 的正例，同时是 save 的负例。

    线上 system prompt 里这是「# 记忆使用规则」唯一用「**必须**」的一条：
    「对话中推断出的长期稳定信息必须调用 propose_core_memory 创建待确认候选，
      绝不能通过 save_core_memory 直接落成正式记忆。」

    2026-08-19 之前 `propose_core_memory` 的正例是 **0 条**（全语料零次调用），
    而判分器把模型自己学会的 propose 算成了误触发（交接文档 5.29）。

    ⚠️ 语义参数逐条从种子读，生成器一个都不猜 —— memory_key / content /
    category 是「用户到底说了什么」，不是「参数怎么填进 JSON」。
    """
    cfg = yaml.safe_load(SCENARIO_SEEDS.read_text(encoding="utf-8"))["S004"]["phrasings"]

    for i, item in enumerate(cfg["推断出稳定信息"]):
        missing = [k for k in ("q", "memory_key", "content", "category") if not item.get(k)]
        if missing:
            raise SystemExit(
                f"seeds/scenarios.yaml 的 S004.推断出稳定信息 第 {i} 条缺 {missing}：{item!r}\n"
                "这几项是语义标签，必须逐条写在种子里（5.19 / 5.22）。"
            )
        args = {"memory_key": item["memory_key"], "content": item["content"],
                "category": item["category"]}
        result = fixtures.propose_core_memory(**args)
        cand = result["candidate"]
        kind = cand["candidate_type"]
        if kind == "replace":
            old = fixtures.memory_store(cand["memory_key"])[cand["memory_key"]]["content"]
            answer = PROPOSE_REPLIES["replace"].format(
                key=cand["memory_key"], old=old, content=cand["proposed_content"])
        else:
            answer = PROPOSE_REPLIES["create"].format(content=cand["proposed_content"])
        out.append(mk(
            f"propose_pos_{i:03d}",
            f"mem__propose__{kind}__{args['memory_key']}__{i:03d}",
            "single_tool_call",
            # save 必须在场：这条边界考的就是「推断出来的走 propose，不走 save」。
            ["propose_core_memory", "save_core_memory", "get_core_memories"],
            [Turn(role="user", content=item["q"]),
             Turn(role="tool_call", calls=[ToolCall("propose_core_memory", args)]),
             Turn(role="tool_result", results=[ToolResult("propose_core_memory", result)]),
             Turn(role="assistant", content=answer)],
            version, rng, all_names))


def main() -> int:
    """运行当前模块的命令行入口。"""
    rng = random.Random(20260810)
    cfg = yaml.safe_load(SEEDS.read_text(encoding="utf-8"))
    schemas, version = load_schemas(SCHEMAS)
    all_names = [s["function"]["name"] for s in schemas]
    out: list[Sample] = []

    for group in ("meta", "gate_save_memory", "gate_delete_memory",
                  "gate_record_answer", "gate_search_memory"):
        gen_no_call(group, cfg[group], version, rng, all_names, out)
    gen_traps(cfg, version, rng, all_names, out)
    gen_memory_positives(version, rng, all_names, out)
    gen_propose_positives(version, rng, all_names, out)

    dump_samples(out, OUT)
    from collections import Counter

    print(f"生成 {len(out)} 条 → {OUT.relative_to(ROOT)}")
    for cat, n in sorted(Counter(s.category for s in out).items()):
        print(f"  {cat:20s} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
