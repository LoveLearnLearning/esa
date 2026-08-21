# backend/scripts/dataset/generators/gen_supplement.py

"""补充评测集生成器：**只出评测题，不进训练集，也不进主表那 464 道**。

为什么要单独一个生成器
----------------------
主评测集的三个小分母全都严重成簇（2026-08-19 实测）：

    不调用（FPR 分母）  130 题 / 15 模板 / 最大模板占 67.7%
    追问                 32 题 /  4 模板 / 最大模板占 46.9%
    拒绝                  6 题 /  6 模板

于是「误触发率 23.8%」有三分之二的重量压在一个场景上，
「拒绝命中率 60%」的 95% 区间宽到 [23, 88]。补分母是唯一的办法，
而**补的必须是互不相同的场景**，不是同一模板的改写 —— 补改写只会让簇更大。

为什么不直接往 `refusals.yaml` / `negatives.yaml` 里加
------------------------------------------------------
`evalset.build()` 挑评测模板的方式是「按类别配额 + `rng.shuffle(pool)`」，
而 `random.shuffle` 消耗的随机数与 `len(pool)` 成正比 ——
**任何一个类别多几个模板，后面所有类别抽到的模板都会跟着变**。
那 464 道题的题面就不是原来那套了，
而「这张表只能和作业 77999 那版基线比」是对外表述的硬约束。

所以这些样本的 `template_id` 一律以 `supp__` 开头，
`evalset.build()` 在建 pool **之前**就把它们摘出去（`SUPPLEMENT_PREFIXES`），
主评测集因此逐字节不变。

用法：
    python3 dataset/generators/gen_supplement.py
"""

from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esa.ir import (  # noqa: E402
    Sample, ToolCall, ToolResult, Turn, dump_samples, load_schemas,
)
from esa.tools_exec import execute  # noqa: E402
from esa.render import pick_tool_names  # noqa: E402
from esa.system_prompt import system_for  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / "dataset/seeds/supplement.yaml"
SCHEMAS = ROOT / "dataset/schemas/tool_schemas.json"
OUT = ROOT / "dataset/data/ir/supplement.jsonl"
SOURCE = "gen_supplement.py"

# 这个前缀是与 `evalset.SUPPLEMENT_PREFIXES` 的约定。改这里必须同时改那边，
# 否则补充样本会悄悄漏进训练集或主评测集 —— 两种后果都不会有任何东西报错。
PREFIX = "supp__"


def main() -> int:
    """运行当前模块的命令行入口。"""
    rng = random.Random(20260819)
    cfg = yaml.safe_load(SEEDS.read_text(encoding="utf-8"))
    schemas, version = load_schemas(SCHEMAS)
    all_names = [s["function"]["name"] for s in schemas]
    by_name = {s["function"]["name"]: s for s in schemas}

    out: list[Sample] = []

    def add(sid: str, tpl: str, category: str, lures: list[str],
            turns: list[Turn], **kw) -> None:
        """一条样本 = 一个模板。补充集里绝不出现「同模板多改写」。"""
        assert tpl.startswith(PREFIX), f"{tpl} 没带 {PREFIX} 前缀，会漏进主评测集"
        out.append(Sample(
            id=sid, template_id=tpl, category=category, schema_version=version,
            system=system_for(turns),
            # 诱饵必须在场：不给工具，模型就没机会学会「给了也别调」。
            tool_names=pick_tool_names(list(lures), all_names, rng),
            source=SOURCE, turns=turns, **kw,
        ))

    # ---- 一、REFUSE ----
    for group, body in cfg["refuse"].items():
        for i, item in enumerate(body["pairs"]):
            # 每条都必须写明「拒的是什么」。写不出来，多半说明这条根本不该是拒绝题
            # —— 5.6 那个「其实该调另一个工具」的错误栽过四次。
            assert item.get("refuse"), f"refuse/{group}[{i}] 没写 refuse 字段"
            add(f"supp_refuse_{group}_{i:02d}",
                f"{PREFIX}refuse__{group}__{i:02d}", "refusal", body["lures"],
                [Turn(role="user", content=item["q"]),
                 Turn(role="assistant", content=item["a"].strip())],
                score_exclude=dict(item.get("score_exclude") or {}))

    # ---- 二、ASK_USER ----
    for item in cfg["ask"]:
        # `ask_for` 必须是在场某个工具的 required 参数，否则「只询问缺失信息」
        # 这条契约就无从验证。这里先自查一遍，别等 validate 再报。
        required_anywhere: set[str] = set()
        for tool in item["lures"]:
            spec = by_name.get(tool)
            if spec:
                required_anywhere |= set(
                    spec["function"].get("parameters", {}).get("required", []))
        for param in item["ask_for"]:
            assert param in required_anywhere, (
                f"ask/{item['id']}：{param!r} 对 lures 里任何工具都不是必填参数")
        add(f"supp_ask_{item['id']}", f"{PREFIX}ask__{item['id']}",
            "clarify", item["lures"],
            [Turn(role="user", content=item["q"]),
             Turn(role="assistant", content=item["a"].strip())],
            ask_for=list(item["ask_for"]))

    # ---- 三、hard_negative ----
    for group, body in cfg["negative"].items():
        for i, item in enumerate(body["pairs"]):
            add(f"supp_neg_{group}_{i:02d}",
                f"{PREFIX}neg__{group}__{i:02d}", "hard_negative", body["lures"],
                [Turn(role="user", content=item["q"]),
                 Turn(role="assistant", content=item["a"].strip())],
                # 字面陷阱那组正文里有事实内容。补充集是评测题、正文不参与判分，
                # 但仍如实标出来，免得日后有人把它当成核验过的讲解语料拿去训练。
                needs_review=(group == "字面陷阱"))

    # ---- 四、CALL_TOOL 边界（2026-08-19 晚新增，理由见种子文件第四节）----
    #
    # 唯一一组带工具调用的补充题。考的是 save / propose 这条边界的**两个方向**，
    # 两个工具永远同时在场。判据是 system prompt 的「# 记忆使用规则」原文：
    #   本轮明确要求记住 → save；只是推断出来的稳定信息 → **必须** propose。
    #
    # ⚠️ 带工具调用的样本会出**两道题**（切在 tool_call 是「调不调、调哪个、
    # 参数对不对」，切在 tool_result 之后是「工具返回后怎么说」），
    # 所以 4 条样本 = 8 道题。补充集从 44 道变 52 道，别再对着 44 断言。
    for item in cfg.get("boundary", []):
        tool, args = item["tool"], item["args"]
        if tool == "save_core_memory":
            # `known` 决定走 created / unchanged / confirmation_required 哪一支，
            # 和 gen_negatives 同一条规矩：它是语义标签，必须显式写在种子里。
            from esa import fixtures  # noqa: PLC0415
            result = fixtures.save_core_memory(
                **args, known=fixtures.memory_store(*item["known"]))
        else:
            result = execute(tool, args)
        add(f"supp_boundary_{item['id']}", f"{PREFIX}boundary__{item['id']}",
            "single_tool_call", item["lures"],
            [Turn(role="user", content=item["q"]),
             Turn(role="tool_call", calls=[ToolCall(tool, args)]),
             Turn(role="tool_result", results=[ToolResult(tool, result)]),
             Turn(role="assistant", content=item["a"].strip())],
            score_exclude=dict(item.get("score_exclude") or {}))

    # ---- 反向检查：种子里声明的作废，必须条条落进样本 ----
    #
    # `score_exclude` 是靠各段自己传进 add() 的。哪天有人把它写进
    # ask / negative 那两段（现在没接线），YAML 看着标了、产出里其实没有 ——
    # 那正是「以为标了、其实没标」的假绿灯。所以两边数一遍，对不上就炸。
    def declared(node) -> int:
        """递归数一数种子里写了几处 score_exclude。"""
        if isinstance(node, dict):
            n = 1 if node.get("score_exclude") else 0
            return n + sum(declared(v) for k, v in node.items() if k != "score_exclude")
        if isinstance(node, list):
            return sum(declared(v) for v in node)
        return 0

    # 指标名也在这里核一遍。判分器里那道 ValueError 当然也拦得住，
    # 但它要等到**超算上判分**才会响；在本机生成这一步炸掉，早得多。
    # （`esa.validate` 里做不了：`eval` 用着 `validate.is_refusal`，反向 import 会成环。
    #  所以照本文件已有的惯例走局部 import。）
    from esa.eval import METRIC_KEYS  # noqa: PLC0415
    for x in out:
        for metric in x.score_exclude:
            assert metric in METRIC_KEYS, (
                f"{x.id}: score_exclude 里的 {metric!r} 不是已知指标名 —— "
                f"写错的指标名什么也不会作废，是个假绿灯")

    want_exc, got_exc = declared(cfg), sum(1 for x in out if x.score_exclude)
    assert want_exc == got_exc, (
        f"种子里声明了 {want_exc} 处 score_exclude，只有 {got_exc} 处落进样本 —— "
        f"多半是写在了还没接线的那一段（现在只有 refuse / boundary 接了）")
    if got_exc:
        print(f"  声明作废 {got_exc} 条（理由随评测集落盘，报告里会逐条印出来）")

    dump_samples(out, OUT)
    print(f"生成 {len(out)} 条 → {OUT.relative_to(ROOT)}")
    print(f"  模板数 {len({s.template_id for s in out})}"
          f"（应当等于条数 —— 补充集一条一个模板，不做同模板改写）")
    for c, n in sorted(Counter(s.category for s in out).items()):
        print(f"  {c:16s} {n}")
    bad = [s.template_id for s in out if not s.template_id.startswith(PREFIX)]
    assert not bad, f"以下模板没带 {PREFIX} 前缀，会漏进主评测集：{bad}"
    return 0


if __name__ == "__main__":
    sys.exit(main())
