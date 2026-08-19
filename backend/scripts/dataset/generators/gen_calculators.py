# backend/scripts/dataset/generators/gen_calculators.py

"""三计算器生成器：正样本 + 困难负样本。

分工原则见计划第一节：
  - 程序负责：参数枚举、真实执行、角色拼装、tools 子集采样  ← 就是这个文件
  - 教师负责：问什么、怎么问、讲解正文                      ← 在 seeds/calculators.yaml

工具返回值一律真实执行（tools_exec），绝不编造。

用法：
    python dataset/generators/gen_calculators.py
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
from esa.tools_exec import execute, latex_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / "dataset/seeds/calculators.yaml"
SCHEMAS = ROOT / "dataset/schemas/tool_schemas.json"
OUT = ROOT / "dataset/data/ir/calculators.jsonl"

SOURCE = "gen_calculators.py"


def _fmt_number(v) -> str:
    """处理 `_fmt_number` 相关逻辑。"""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def gen_calculator(seeds, rng, all_names, version, systems) -> list[Sample]:
    """处理 `gen_calculator` 相关逻辑。

    Args:
        seeds: object => `seeds` 参数。
        rng: object => `rng` 参数。
        all_names: object => `all_names` 参数。
        version: object => `version` 参数。
        systems: object => `systems` 参数。

    Returns:
        list[Sample] => 处理结果。
    """
    out = []
    for idx, seed in enumerate(seeds):
        expr = seed["expr"]
        result = execute("calculator", {"expression": expr})
        # 线上字段是 result，不是 value（calculator.py:167-170）。
        value = _fmt_number(result["result"])
        for j, phrasing in enumerate(seed["phrasings"]):
            query = phrasing.format(e=expr)
            if seed.get("ctx"):
                query = f"{seed['ctx']}{query}"
            answer = f"结果是 ${value}$。"
            turns = [
                Turn(role="user", content=query),
                Turn(role="tool_call", calls=[ToolCall("calculator", {"expression": expr})]),
                Turn(role="tool_result", results=[ToolResult("calculator", result)]),
                Turn(role="assistant", content=answer),
            ]
            out.append(
                Sample(
                    id=f"calc_{idx:03d}_{j}",
                    template_id=f"calculator__{expr}",
                    category="single_tool_call",
                    schema_version=version,
                    system=system_for(turns),
                    tool_names=pick_tool_names(["calculator"], all_names, rng),
                    source=SOURCE,
                    turns=turns,
                )
            )
    return out


def gen_math_solver(seeds, rng, all_names, version, systems) -> list[Sample]:
    """处理 `gen_math_solver` 相关逻辑。

    Args:
        seeds: object => `seeds` 参数。
        rng: object => `rng` 参数。
        all_names: object => `all_names` 参数。
        version: object => `version` 参数。
        systems: object => `systems` 参数。

    Returns:
        list[Sample] => 处理结果。
    """
    out = []
    for idx, seed in enumerate(seeds):
        args = {"operation": seed["op"], "expression": seed["expr"], "variable": seed["var"]}
        args.update(seed.get("extra") or {})
        result = execute("math_solver", args)
        # ⚠️ 线上返回里**没有 latex 字段**（math_solver.py:293-296），只有纯文本 result。
        # 把 sympy 字符串渲染成 LaTeX 是模型自己该做的一步
        # （`skills/math_problem_solving.md`「数学排版」段要求包在 $ 里；
        #  ~~原先是 MATH_PRMOPT~~，那个文件 2026-08-11 已被后端删除），
        # 所以这里由教师示范，而不是去读一个线上不存在的键。
        for j, phrasing in enumerate(seed["phrasings"]):
            query = phrasing.format(e=seed["expr"])
            answer = f"结果是 ${latex_of(result['result'])}$。"
            turns = [
                Turn(role="user", content=query),
                Turn(role="tool_call", calls=[ToolCall("math_solver", args)]),
                Turn(role="tool_result", results=[ToolResult("math_solver", result)]),
                Turn(role="assistant", content=answer),
            ]
            out.append(
                Sample(
                    id=f"msolve_{idx:03d}_{j}",
                    template_id=f"math_solver__{seed['op']}__{seed['expr']}",
                    category="single_tool_call",
                    schema_version=version,
                    system=system_for(turns),
                    tool_names=pick_tool_names(["math_solver"], all_names, rng),
                    source=SOURCE,
                    turns=turns,
                )
            )
    return out


def gen_bitwise(seeds, rng, all_names, version, systems) -> list[Sample]:
    """处理 `gen_bitwise` 相关逻辑。

    Args:
        seeds: object => `seeds` 参数。
        rng: object => `rng` 参数。
        all_names: object => `all_names` 参数。
        version: object => `version` 参数。
        systems: object => `systems` 参数。

    Returns:
        list[Sample] => 处理结果。
    """
    out = []
    for idx, seed in enumerate(seeds):
        expr = seed["expr"]
        result = execute("bitwise_calculator", {"expression": expr})
        # 线上是 result + formats（bitwise_calculator.py:165-169），
        # formats 里是 decimal / binary / octal / hexadecimal / bit_length / popcount。
        value = _fmt_number(result["result"])
        binary = (result.get("formats") or {}).get("binary")
        for j, phrasing in enumerate(seed["phrasings"]):
            query = phrasing.format(e=expr)
            if seed.get("ctx"):
                query = f"{seed['ctx']}{query}"
            answer = f"结果是 ${value}$"
            if binary:
                answer += f"，二进制是 `{binary}`"
            answer += "。"
            turns = [
                Turn(role="user", content=query),
                Turn(role="tool_call", calls=[ToolCall("bitwise_calculator", {"expression": expr})]),
                Turn(role="tool_result", results=[ToolResult("bitwise_calculator", result)]),
                Turn(role="assistant", content=answer),
            ]
            out.append(
                Sample(
                    id=f"bitw_{idx:03d}_{j}",
                    template_id=f"bitwise__{expr}",
                    category="single_tool_call",
                    schema_version=version,
                    system=system_for(turns),
                    tool_names=pick_tool_names(["bitwise_calculator"], all_names, rng),
                    source=SOURCE,
                    turns=turns,
                )
            )
    return out


def gen_hard_negatives(seeds, rng, all_names, version, systems) -> list[Sample]:
    """给了工具却不该调 —— 训练的是「工具选择边界」。

    tool_names 里必须放上那个「诱饵工具」，否则模型根本没机会学会不调它。
    """
    lures = ["calculator", "math_solver", "bitwise_calculator", "get_time", "recommend_practice",
             "get_mastery_report", "save_core_memory", "get_core_memories", "record_answer"]
    out = []
    for idx, seed in enumerate(seeds):
        # 一个种子只出一条。曾经为了「增强信号」把同一句话配不同诱饵渲染两次，
        # 结果就是字面重复 —— 而 pick_tool_names 本来就按样本随机采工具子集，
        # 「有工具也别调」的信号在语料层面已经由不同种子之间的随机化提供了。
        required = rng.sample(lures, 3)
        turns = [
            Turn(role="user", content=seed["query"]),
            Turn(role="assistant", content=seed["answer"].strip()),
        ]
        out.append(
            Sample(
                id=f"hardneg_{idx:03d}",
                template_id=f"hardneg__{idx:03d}",
                category="hard_negative",
                schema_version=version,
                system=system_for(turns),
                tool_names=pick_tool_names(required, all_names, rng),
                source=SOURCE,
                topic=seed.get("topic", ""),
                needs_review=True,  # 讲解正文是写作类内容，无法自动核验
                turns=turns,
            )
        )
    return out


def main() -> int:
    """运行当前模块的命令行入口。"""
    rng = random.Random(20260804)
    seeds = yaml.safe_load(SEEDS.read_text(encoding="utf-8"))
    schemas, version = load_schemas(SCHEMAS)
    all_names = [s["function"]["name"] for s in schemas]
    systems = seeds["system_prompts"]

    samples = (
        gen_calculator(seeds["calculator"], rng, all_names, version, systems)
        + gen_math_solver(seeds["math_solver"], rng, all_names, version, systems)
        + gen_bitwise(seeds["bitwise_calculator"], rng, all_names, version, systems)
        + gen_hard_negatives(seeds["hard_negatives"], rng, all_names, version, systems)
    )

    dump_samples(samples, OUT)
    from collections import Counter

    print(f"生成 {len(samples)} 条 → {OUT.relative_to(ROOT)}")
    for cat, n in sorted(Counter(s.category for s in samples).items()):
        print(f"  {cat:20s} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
