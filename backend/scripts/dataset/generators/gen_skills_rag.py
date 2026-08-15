# backend/scripts/dataset/generators/gen_skills_rag.py

"""load_skill 与 RAG 的数据生成器。

load_skill —— 观测值是**调后端真实 load_skill() 抓来的正文**
  （data/cache/skills_bodies.json，由 tools/capture_skill_bodies.py 产出），零编造。
  失败观测用真实的 "{name} skill not found!"，文案同样取自那次抓取。

⚠️ 2026-08-11 后端加了确定性路由之后，这里多了一个必须处理的情况：
  路由命中时后端会把 Skill 正文**直接注入 system prompt**，并写明
  「该 Skill 由系统内部加载，无需再调用 load_skill」
  （pedagogy_router.py:52-62 / agent.py:150-160）。
  这种消息如果还教模型调 load_skill，样本就和它自己的 system prompt 直接打架 ——
  等于训练模型无视系统指令。所以正例前先查一次真实路由结果，命中的那些改成
  「已自动加载 → 直接执行，不要再调」的负样本。

RAG —— 只做负样本与约束样本。retrieve_knowledge 的返回依赖真实语料库，
  不知道索引了哪些文档就生成正例，等于编造可追溯来源，而「内容可追溯」
  是赛题明写的评分项。正例需要 RAG 负责人提供真实检索导出。

用法：
    python3 dataset/generators/gen_skills_rag.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa.ir import Sample, ToolCall, ToolResult, Turn, dump_samples, load_schemas  # noqa: E402
from esa.render import pick_tool_names  # noqa: E402
from esa.system_prompt import routed_skill, skill_names, system_for  # noqa: E402
from esa.tools_exec import execute  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / "dataset/seeds/skills_rag.yaml"
BODIES = ROOT / "dataset/data/cache/skills_bodies.json"
SCHEMAS = ROOT / "dataset/schemas/tool_schemas.json"
OUT = ROOT / "dataset/data/ir/skills_rag.jsonl"
SOURCE = "gen_skills_rag.py"


def load_bodies() -> tuple[dict[str, str], str]:
    """读缓存里 `load_skill()` 的真实返回值，以及未知 skill 的失败文案。

    以前这里自己写正则剥 frontmatter（`re.split(r"^---\\s*$", ...)`）——
    那是复刻后端 `_parse_skill` 的剥法。现在缓存里存的就是 `load_skill()` 的返回值本身，
    这一步没有了：能跑就别想（交接文档第五节第 4 条）。
    """
    raw = json.loads(BODIES.read_text(encoding="utf-8"))
    if "bodies" not in raw:
        raise SystemExit(
            f"{BODIES.name} 是旧格式（整份文件文本）。重抓：\n"
            "  python3 dataset/tools/capture_skill_bodies.py"
        )
    return raw["bodies"], raw["_meta"]["not_found_template"]


def mk(sid, tpl, category, tools, turns, version, rng, all_names, review=False):
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
        review: object => `review` 参数。

    Returns:
        object => 处理结果。
    """
    return Sample(
        id=sid, template_id=tpl, category=category, schema_version=version,
        system=system_for(turns),
        tool_names=pick_tool_names(tools, all_names, rng),
        source=SOURCE, needs_review=review, turns=turns,
    )


# 加载 Skill 之后的**默认**回应：按正文执行，而不是复述正文。
# system prompt 要求「当任务与某 Skill 匹配时先加载完整正文，再按正文执行」。
#
# ⚠️ 这个字典按 skill 名写死。种子库里 `正例` 引用了哪个 skill，这里就必须有对应话术，
# 否则下面那句 `FOLLOW_UP[skill]` 会 KeyError。这是**故意**让它炸的：
# 用 .get() 兜个空串的话，那一组样本会静默变成"加载完 Skill 之后什么也不说"，
# 没有任何检查拦得住（交接文档第五节规矩 2：绝不吞异常）。
# 新增 skill 的正例之前，先在这里补一条回应话术。
#
# ⚠️ 「默认」二字是 2026-08-12 复核之后加的，别再把它当成"这个 skill 的唯一回答"。
# 一句话按 skill 复用到该 skill 的每条 query，只有在这句话对每条 query 都成立时才对。
# homework_review 就栽在这儿：默认话术在点评一段冒泡排序代码，而三条 query 里
# 只有第一条真的给了代码，另外两条被训成了凭空批改不存在的作业。
# 话术里只要出现「你这段/这道题的具体内容」，就必须去 seeds 里给每条 query 单独写 `a`。
FOLLOW_UP = {
    "homework_review": "我按批改流程来看：先确认你的思路，再定位具体问题。你这段代码的内层循环边界 `range(n)` 会让 `a[j+1]` 越界，应该是 `range(n-1-i)`。先改这一处，再跑一遍看看？",
    "progressive_hint": "那我给你第一级提示，先不碰具体做法：想想这个问题的输入规模决定了你能用多高的复杂度——这一步能圈定算法范围。还需要下一级提示吗？",
    "error_diagnosis": "要定位根源，我需要看具体是哪一类错。你把这几次做错的题发我，或者告诉我错在哪一步——我判断一下是概念没通、步骤记错，还是前置知识的问题。",
    "teach_back": "好，你讲，我不打断。讲完我会指出哪些点说清楚了、哪些还有缺口，缺口部分我们再补。",
    "study_plan": "那我按剩余时间和你的真实掌握情况来排。先确认两件事：是哪门课，距离考试还有几周？",
    "retrieve_first": "在讲之前先做个低成本回忆——你现在对这个概念知道多少？哪怕只记得一两句也说说，我针对缺口讲会更有效率。",
}


def gen_load_skill(cfg, bodies, not_found_template, version, rng, all_names, out):
    """处理 `gen_load_skill` 相关逻辑。

    Args:
        cfg: object => `cfg` 参数。
        bodies: object => `bodies` 参数。
        not_found_template: object => `not_found_template` 参数。
        version: object => `version` 参数。
        rng: object => `rng` 参数。
        all_names: object => `all_names` 参数。
        out: object => `out` 参数。
    """
    routed_hits = 0
    for item in cfg["load_skill"]["正例"]:
        skill = item["skill"]
        body = bodies[skill]
        # 先取一次默认话术，缺了就在这里 KeyError —— 即使每条 query 都自带 `a`，
        # 这个"新增 skill 必须补话术"的约束也不能因为没人用到默认值就悄悄失效。
        default_reply = FOLLOW_UP[skill]
        for j, spec in enumerate(item["queries"]):
            q = spec["q"]
            reply = spec.get("a") or default_reply
            if routed_skill(q) == skill:
                # 后端确定性路由已经命中同一个 Skill，正文此刻就在 system prompt 里，
                # 而且那段文字明写「无需再调用 load_skill」。再教模型调一次，
                # 训的就是"无视系统指令"。改成教它直接按已注入的正文执行。
                routed_hits += 1
                out.append(mk(
                    f"skill_autoloaded_{skill}_{j:02d}", f"skill__已路由注入__{skill}__{j:02d}",
                    "hard_negative", ["load_skill"],
                    [Turn(role="user", content=q),
                     Turn(role="assistant", content=reply)],
                    version, rng, all_names, review=True))
                continue
            out.append(mk(
                f"skill_{skill}_{j:02d}", f"skill__{skill}__{j:02d}", "single_tool_call",
                ["load_skill"],
                [Turn(role="user", content=q),
                 Turn(role="tool_call", calls=[ToolCall("load_skill", {"name": skill})]),
                 Turn(role="tool_result", results=[ToolResult("load_skill", body)]),
                 Turn(role="assistant", content=reply)],
                version, rng, all_names, review=True))
    print(f"  正例里有 {routed_hits} 条被后端路由自动加载 → 改判为「不要再调 load_skill」的负样本")

    # 不存在的 Skill —— 真实失败观测
    names = skill_names()
    for j, item in enumerate(cfg["load_skill"]["不存在的skill"]):
        name = item["name"]
        err = not_found_template.format(name=name)
        reply = (f"没有「{name}」这个技能。我目前可用的是："
                 f"{'、'.join(names[:5])} 等。你想做的事更接近哪一类？我不会编一个不存在的流程出来。")
        out.append(mk(
            f"skill_404_{j:02d}", f"skill__notfound__{j:02d}", "tool_error",
            ["load_skill"],
            [Turn(role="user", content=item["q"]),
             Turn(role="tool_call", calls=[ToolCall("load_skill", {"name": name})]),
             Turn(role="tool_result", results=[ToolResult("load_skill", err, is_error=True)]),
             Turn(role="assistant", content=reply)],
            version, rng, all_names))

    for group in ("混淆_不该加载", "混淆_已自动加载"):
        for j, item in enumerate(cfg["load_skill"][group]):
            out.append(mk(
                f"skill_neg_{group[-4:]}_{j:02d}", f"skill__{group}__{j:02d}", "hard_negative",
                ["load_skill", "recommend_practice", "calculator"],
                [Turn(role="user", content=item["q"]),
                 Turn(role="assistant", content=item["a"])],
                version, rng, all_names))


def gen_wrong_tool(cfg, section, version, rng, all_names, out):
    """「该调另一个工具」的混淆样本 —— 不是「什么都不调」。

    这组是从 `混淆_不该加载` / `混淆_不该检索` 里挪出来的：
    「帮我算 2 的 16 次方」的正确行为是调 calculator，标成 hard_negative 等于
    教模型连该干的活也别干（交接文档 5.6，这个错误已经第四次了）。

    教学意图一点没丢 —— 诱饵工具仍然在场，回答里也仍然点明「不用查知识库 / 不用加载技能」，
    只是标签从「不调用」改成了「调对的那个」。
    """
    for j, item in enumerate(cfg[section].get("混淆_应调其它工具", [])):
        tool, args = item["tool"], item["args"]
        result = execute(tool, args)
        # 回答模板可以引用真实返回值，保证 grounding 检查过得去
        fields = {"value": result.get("result"), **{k: v for k, v in result.items()
                                                    if isinstance(v, (str, int, float))}}
        out.append(mk(
            f"{section}_wrongtool_{j:02d}", f"{section}__应调其它工具__{j:02d}",
            "single_tool_call", [tool, item["lure"]],
            [Turn(role="user", content=item["q"]),
             Turn(role="tool_call", calls=[ToolCall(tool, args)]),
             Turn(role="tool_result", results=[ToolResult(tool, result)]),
             Turn(role="assistant", content=item["a"].format(**fields))],
            version, rng, all_names))


def gen_rag(cfg, version, rng, all_names, out):
    """处理 `gen_rag` 相关逻辑。

    Args:
        cfg: object => `cfg` 参数。
        version: object => `version` 参数。
        rng: object => `rng` 参数。
        all_names: object => `all_names` 参数。
        out: object => `out` 参数。
    """
    for j, item in enumerate(cfg["rag"]["混淆_不该检索"]):
        out.append(mk(
            f"rag_neg_{j:02d}", f"rag__不该检索__{j:02d}", "hard_negative",
            ["retrieve_knowledge", "get_knowledge_base_stats", "calculator"],
            [Turn(role="user", content=item["q"]),
             Turn(role="assistant", content=item["a"])],
            version, rng, all_names, review=True))

    for j, item in enumerate(cfg["rag"]["参数约束"]):
        out.append(mk(
            f"rag_param_{j:02d}", f"rag__参数约束__{j:02d}", "hard_negative",
            ["retrieve_knowledge", "get_knowledge_base_stats"],
            [Turn(role="user", content=item["q"]),
             Turn(role="assistant", content=item["a"])],
            version, rng, all_names))


def main() -> int:
    """运行当前模块的命令行入口。"""
    rng = random.Random(20260810)
    cfg = yaml.safe_load(SEEDS.read_text(encoding="utf-8"))
    bodies, not_found_template = load_bodies()
    schemas, version = load_schemas(SCHEMAS)
    all_names = [s["function"]["name"] for s in schemas]
    out: list[Sample] = []

    gen_load_skill(cfg, bodies, not_found_template, version, rng, all_names, out)
    gen_wrong_tool(cfg, 'load_skill', version, rng, all_names, out)
    gen_wrong_tool(cfg, 'rag', version, rng, all_names, out)
    gen_rag(cfg, version, rng, all_names, out)

    dump_samples(out, OUT)
    from collections import Counter

    print(f"生成 {len(out)} 条 → {OUT.relative_to(ROOT)}")
    for cat, n in sorted(Counter(s.category for s in out).items()):
        print(f"  {cat:20s} {n}")
    print("\n⚠️  retrieve_knowledge / get_knowledge_base_stats 只有负样本。")
    print("    正例需要 RAG 负责人提供真实语料库的检索导出 —— 不知道索引了哪些文档就造正例，")
    print("    等于编造可追溯来源，而「内容可追溯」是赛题评分项。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
