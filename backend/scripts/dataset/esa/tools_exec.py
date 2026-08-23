# backend/scripts/dataset/esa/tools_exec.py

"""真实执行工具，拿真的返回值当 observation。

绝不让生成模型编造工具结果 —— 一旦编造，模型学到的就是「工具会返回我想要的东西」，
上线之后遇到真实返回值就对不上。

三个计算器走 `data/cache/math_real.json`：那是 `tools/capture_math_outputs.py`
**执行后端真实函数**抓下来的。学情类工具由 fixtures.py 按后端公式真实计算。

⚠️ 教训：这个文件原来自己重写了一版计算器，返回 `{"value": 44}`，
而后端真实返回的是 `{"expression": ..., "result": 44}`；`math_solver` 更是
根本没有 `latex` 字段。63 条样本因此消费了一个线上不存在的结构。
所以现在只查表，查不到就抛错 —— 宁可停下，也不要凭本地实现猜一个出来。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import sympy


class ToolError(Exception):
    """工具执行失败。tool_error 类样本靠它拿到真实的报错文案。"""


# --------------------------------------------------------------------------
# 三个计算器：查后端真实返回值的缓存
#
# 缓存由 tools/capture_math_outputs.py 执行**后端真实函数**产出。
# 这里不做任何本地计算 —— 本地重写一版必然和线上有出入，上一版就是这么错的。
# --------------------------------------------------------------------------

MATH_CACHE = Path(__file__).resolve().parents[2] / "dataset/data/cache/math_real.json"


def _cache_key(tool: str, arguments: dict[str, Any]) -> str:
    """必须和 capture_math_outputs.cache_key 完全一致，否则永远查不中。"""
    return f"{tool}|{json.dumps(arguments, ensure_ascii=False, sort_keys=True)}"


@lru_cache(maxsize=1)
def _math_cache() -> dict[str, Any]:
    """处理 `_math_cache` 相关逻辑。"""
    if not MATH_CACHE.exists():
        raise ToolError(
            f"找不到 {MATH_CACHE}。先跑 python3 dataset/tools/capture_math_outputs.py 抓真实返回值。"
        )
    return json.loads(MATH_CACHE.read_text(encoding="utf-8"))["entries"]


def _from_math_cache(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """查表。查不到就抛错，绝不退回本地实现算一个。

    失败要吵：静默用一个「差不多」的值顶上，就是上一版 63 条样本消费了
    线上不存在的字段却没人发现的原因。
    """
    key = _cache_key(tool, arguments)
    cache = _math_cache()
    if key not in cache:
        raise ToolError(
            f"math_real.json 里没有 {key!r}。"
            f"先把这个调用写进种子库，再跑 dataset/tools/capture_math_outputs.py 重抓，不要就地编一个返回值。"
        )
    return cache[key]


def calculator(expression: str) -> dict[str, Any]:
    """后端真实返回 {"expression": ..., "result": ...}；失败时是 {..., "result": None, "error": ...}。

    注意后端的三个计算器**不抛异常** —— 失败也是正常返回一个带 error 键的 dict
    （calculator.py:145-150），和其余工具那套 `[Error]: {e}` 字符串是两套表示。
    """
    return _from_math_cache("calculator", {"expression": expression})


def bitwise_calculator(expression: str) -> dict[str, Any]:
    """后端真实返回 {"expression": ..., "result": ..., "formats": {...}}（bitwise_calculator.py:165-169）。

    formats 里有 decimal / binary / octal / hexadecimal / bit_length / popcount 六个键。
    """
    return _from_math_cache("bitwise_calculator", {"expression": expression})


def math_solver(**kwargs: Any) -> dict[str, Any]:
    """后端真实返回 {"operation": ..., "expression": ..., "result": str}（math_solver.py:293-296）。

    ⚠️ **没有 latex 字段**。上一版这里编了一个 `sympy.latex(...)`，22 条样本的回答
    正是引用它写的 —— 模型会学会读一个线上永远不会出现的键。
    LaTeX 该由模型自己从 result 渲染，这一步本来就是它的工作。
    """
    return _from_math_cache("math_solver", kwargs)


def latex_of(sympy_result: str) -> str:
    """把 math_solver 返回的 sympy 字符串渲染成 LaTeX，供生成器写回答正文用。

    这不是工具返回值的一部分，是**教师在示范模型该怎么做**：
    后端要求「只对数学表达式使用 LaTeX，行内 `$...$`，独立推导 `$$...$$`」，而工具只给纯文本 result。
    （出处 2026-08-11 起是 `skills/math_problem_solving.md` 的「数学排版」段；
     ~~原先在 `core/message/math_prompt.py` 的 MATH_PRMOPT~~ —— 那个文件已被删除。）
    """
    return sympy.latex(sympy.sympify(sympy_result))


# --------------------------------------------------------------------------
# 需要后端 / 测试数据库的工具
# --------------------------------------------------------------------------

# 学情三件套已由 fixtures.py 用测试学情库真实计算，不在此列。
BACKEND_REQUIRED = {
    "load_skill",
    "retrieve_knowledge_v2",
    "get_knowledge_base_stats",
}

# 这些必须调真实外部 API。
# arxiv_search 尤其不能编造 —— 赛题《02—伦理与安全合规性声明》要求承诺
# 「输出内容不涉及伪造学术数据、虚假文献」，训练数据里编论文等于教模型编引用。
# arxiv_search 走 data/cache/arxiv_real.json 的真实检索结果；
# get_time / get_weather 后端本身就是纯函数/硬编码桩，可完全复刻。
# web_search 需要真实 SearXNG 实例，没有就只做错误恢复样本，不编造检索结果。
EXTERNAL_API = {"web_search"}

CACHED_TOOLS = {
    "calculator": calculator,
    "bitwise_calculator": bitwise_calculator,
    "math_solver": math_solver,
}


def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """执行工具。三个计算器查真实返回值缓存，学情三件套由 fixtures 真实计算，其余抛错。"""
    from .fixtures import FIXTURE_FUNCTIONS  # 延迟导入，避免与 tools_exec 循环依赖

    fn = CACHED_TOOLS.get(name) or FIXTURE_FUNCTIONS.get(name)
    if fn is None:
        if name in BACKEND_REQUIRED:
            raise ToolError(f"{name} 需要后端测试数据库，请接入后端 test fixture 后再生成这类样本")
        if name in EXTERNAL_API:
            raise ToolError(f"{name} 必须调真实 API，禁止伪造返回值")
        raise ToolError(f"未知工具: {name}")
    return fn(**arguments)
