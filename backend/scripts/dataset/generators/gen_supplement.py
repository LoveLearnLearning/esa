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

from esa.ir import Sample, Turn, dump_samples, load_schemas  # noqa: E402
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
                 Turn(role="assistant", content=item["a"].strip())])

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
