"""「有工具在场，但这件事用不上工具」—— 不调用类样本生成器。

为什么补这一批
--------------
架构 V1 的 Task Family 候选空间共 54 项，其中 **37 项后端没有任何工具支撑**
（代码理解、翻译、内容改写、逻辑推理、结构化输出……）。这些方向产出的全是
DIRECT_ANSWER 样本，而"不调用类"配比正是我们最硬的瓶颈 ——
要扩到一万条并保持配比，还需要再手写约 2,200 条。

所以架构那份 Scenario 清单对数据组最直接的用处，不是拿去建新表，
而是当**负样本的选题清单**。这个生成器就是那条接口。

只训正例的后果不是抽象风险：模型会学到先验 P(调用)≈0.94，见什么都想调工具，
demo 现场直接翻车。上一轮把不调用类从 5.9% 修到 23% 花了很大力气。

怎么保证这些请求真的不该调工具
------------------------------
统一用一个能自证的写法：**要处理的内容由用户在问句里直接给出**。
代码贴在问句里、段落贴在问句里、待转换的表格贴在问句里 ——
没有任何东西需要去检索、计算或读学情。

这样"不该调工具"就不是我的判断，而是句子本身的性质。
交接文档 5.6 那个"其实该调 B"的错误栽过四次，这条写法是针对它的。

用法：
    python3 dataset/generators/gen_no_tool_tasks.py
"""

from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa.ir import Sample, Turn, dump_samples, load_schemas  # noqa: E402
from esa.render import pick_tool_names  # noqa: E402
from esa.system_prompt import routed_skill, system_for  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / "dataset/seeds/no_tool_tasks.yaml"
SCHEMAS = ROOT / "dataset/schemas/tool_schemas.json"
OUT = ROOT / "dataset/data/ir/no_tool_tasks.jsonl"
SOURCE = "gen_no_tool_tasks.py"

# 这些工具名一旦出现在**用户问句**里，多半说明这条种子写歪了 ——
# 它其实是"该调那个工具"的请求，不是不调用类。
# 不是完备检查，只是一道便宜的提醒；真正的判据是"内容在问句里给全了"。
_SUSPICIOUS = ("帮我算", "算一下", "等于多少", "搜一下", "查一下天气", "现在几点",
               "我掌握", "学得怎么样", "推荐练习", "记住我")


def main() -> int:
    rng = random.Random(20260812)
    cfg = yaml.safe_load(SEEDS.read_text(encoding="utf-8"))
    schemas, version = load_schemas(SCHEMAS)
    all_names = [s["function"]["name"] for s in schemas]

    out: list[Sample] = []
    warned: list[str] = []
    for group, body in cfg.items():
        lures = body["lures"]
        for i, item in enumerate(body["pairs"]):
            q = item["q"].strip()
            sid = f"notool_{group}_{i:02d}"
            for marker in _SUSPICIOUS:
                if marker in q:
                    warned.append(f"{sid}: 问句里有「{marker}」，确认它不该调工具")
            # 路由命中的话，后端会把某个 Skill 正文注入 system prompt 并要求"按正文执行"，
            # 而这批样本的正确行为是直接把活干掉。两边会起冲突，措辞该绕开。
            # 实测踩过：「为什么…」→ retrieve_first；「不会」→ progressive_hint。
            if (hit := routed_skill(q)) is not None:
                warned.append(f"{sid}: 问句命中路由 {hit}，system prompt 会被注入该 Skill 正文，"
                              "和「直接干活」的回答冲突 —— 换个说法绕开")
            turns = [
                Turn(role="user", content=q),
                Turn(role="assistant", content=item["a"].strip()),
            ]
            out.append(Sample(
                id=sid,
                template_id=f"notool__{group}__{i:02d}",
                category="hard_negative",
                schema_version=version,
                system=system_for(turns),
                # 诱饵必须在场，否则学不到"给了工具也别调"
                tool_names=pick_tool_names(list(lures), all_names, rng),
                source=SOURCE,
                # 回答里有需要外部知识才能判对错的技术断言 → 挂人工复核，
                # 和 gen_negatives.py:98 的 trap 组同一条约定。
                # 纯粹加工用户给定内容的（转表格、压缩、翻译）不挂：
                # 对错在问句里就能看出来，机器验不了但人一眼能核。
                needs_review=bool(item.get("has_facts")),
                turns=turns,
            ))

    dump_samples(out, OUT)
    print(f"生成 {len(out)} 条 → {OUT.relative_to(ROOT)}")
    for g, n in sorted(Counter(s.id.split("_")[1] for s in out).items()):
        print(f"  {g:10s} {n}")
    print(f"  待人工复核 {sum(1 for s in out if s.needs_review)} 条（含技术断言的那些）")
    if warned:
        # 不静默：这类种子最容易写成"其实该调另一个工具"，让人当场看一眼
        print("\n⚠️  下面这些种子需要人看一眼（工具意图词 / 路由命中）：")
        for w in warned:
            print(f"    {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
