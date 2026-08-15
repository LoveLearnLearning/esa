# backend/scripts/dataset/generators/gen_negatives.py

"""负样本生成器：工具在场但不该调用。

配比是当前最大的短板 —— "不调用"类只占 5.9%，目标 23%。只训正例会让模型学到
先验 P(调用)≈0.94，见什么都想调工具。

三类：
  meta        元对话（寒暄/致谢/问系统自身）
  gate_*      提到了但没要求 —— 防止不可逆的记忆写入
  traps       概念题撞上工具名

同时产出 save_core_memory / delete_core_memory 的**正样本**，与 gate 负样本构成对照：
同一个话题，明确要求就调、只是提到就不调。没有这组对照，模型学到的是"别碰记忆工具"，
而不是"看用户有没有明确要求"。

用法：
    python3 dataset/generators/gen_negatives.py
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

# 明确要求保存/删除时该传什么参数。取自 scenarios.yaml 的 S004 话术。
SAVE_ARGS = {
    "记一下，我是软件工程大三的，准备考研":
        {"memory_key": "major_info", "content": "软件工程专业大三，准备考研", "category": "profile"},
    "请记住：我更喜欢先看直观例子，再看公式推导。":
        {"memory_key": "response_style", "content": "先看直观例子，再看公式推导", "category": "preference"},
    "帮我存个学习目标——这学期把数据结构和算法吃透":
        {"memory_key": "learning_goal", "content": "这学期把数据结构和算法吃透", "category": "learning"},
    "以后回答简短一点，记住这个偏好":
        {"memory_key": "response_style", "content": "回答尽量简短", "category": "preference"},
    "记下来，我的期末考试从第 16 周开始":
        {"memory_key": "exam_schedule", "content": "期末考试从第 16 周开始", "category": "constraint"},
}
DELETE_ARGS = {
    "把我之前设的学习目标删掉吧": "learning_goal",
    "忘掉你记的我的回答风格偏好": "response_style",
    "请删除关于我薄弱知识点的那条记忆。": "weak_topics",
    "我不想让你再记着我的考试安排了，删了它": "exam_schedule",
    "之前存的那个学习目标不作数了，清掉": "learning_goal",
    "帮我把回答风格那条记忆去掉": "response_style",
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

    for i, q in enumerate(cfg["明确要求记住"]):
        args = SAVE_ARGS.get(q)
        if args is None:
            print(f"    ⚠️  没有为 {q!r} 配置 save 参数，已跳过")
            continue
        result = execute("save_core_memory", args)
        out.append(mk(
            f"save_pos_{i:03d}", f"mem__save__{args['memory_key']}__{i:03d}",
            "single_tool_call", ["save_core_memory", "delete_core_memory"],
            [Turn(role="user", content=q),
             Turn(role="tool_call", calls=[ToolCall("save_core_memory", args)]),
             Turn(role="tool_result", results=[ToolResult("save_core_memory", result)]),
             Turn(role="assistant",
                  content=f"记住了：{result['content']}。之后我会按这个来。")],
            version, rng, all_names))

    for i, q in enumerate(cfg["明确要求删除"]):
        key = DELETE_ARGS.get(q)
        if key is None:
            print(f"    ⚠️  没有为 {q!r} 配置 delete 参数，已跳过")
            continue
        result = execute("delete_core_memory", {"memory_key": key})
        out.append(mk(
            f"del_pos_{i:03d}", f"mem__delete__{key}__{i:03d}",
            "single_tool_call", ["delete_core_memory", "save_core_memory"],
            [Turn(role="user", content=q),
             Turn(role="tool_call", calls=[ToolCall("delete_core_memory", {"memory_key": key})]),
             Turn(role="tool_result", results=[ToolResult("delete_core_memory", result)]),
             Turn(role="assistant",
                  content=f"已经删掉「{result['memory_key']}」这条记忆了。")],
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

    dump_samples(out, OUT)
    from collections import Counter

    print(f"生成 {len(out)} 条 → {OUT.relative_to(ROOT)}")
    for cat, n in sorted(Counter(s.category for s in out).items()):
        print(f"  {cat:20s} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
