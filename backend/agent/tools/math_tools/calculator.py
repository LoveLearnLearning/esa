# backend/agent/tools/math_tools/calculator.py

"""安全的数学计算器工具

使用 AST 解析与白名单求值器，不使用 eval()，防止代码注入。
支持四则运算、幂运算、科学函数和数学常量。
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any, ClassVar

from backend.agent.tools.math_tools._base_evaluator import BaseSafeEvaluator
from backend.agent.tools.tools import tr

# 兼容 Python 3.10（math.cbrt 自 3.11 起存在）
try:
    _cbrt = math.cbrt  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover

    def _cbrt(x: float) -> float:
        """处理 `_cbrt` 相关逻辑。"""
        return math.copysign(abs(x) ** (1.0 / 3.0), x)


class _MathEvaluator(BaseSafeEvaluator):
    """数学计算器 AST 求值器"""

    _REPLACE_CARET: ClassVar[bool] = True

    _BIN_OPS: ClassVar[dict[type, Any]] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }

    _UNARY_OPS: ClassVar[dict[type, Any]] = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    _FUNCTIONS: ClassVar[dict[str, Any]] = {
        # 基础函数
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        # 取整
        "floor": math.floor,
        "ceil": math.ceil,
        "trunc": math.trunc,
        # 幂与根
        "sqrt": math.sqrt,
        "cbrt": _cbrt,
        "exp": math.exp,
        "pow": pow,
        # 对数
        "ln": math.log,  # 自然对数（底 e）
        "log": math.log10,  # 常用对数（底 10）
        "log2": math.log2,
        "log10": math.log10,
        # 三角函数（弧度制）
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "asin": math.asin,
        "acos": math.acos,
        "atan": math.atan,
        # 双曲函数
        "sinh": math.sinh,
        "cosh": math.cosh,
        "tanh": math.tanh,
        # 角度转换
        "degrees": math.degrees,
        "radians": math.radians,
        # 数论
        "factorial": math.factorial,
        "gcd": math.gcd,
        # 其他
        "hypot": math.hypot,
        "copysign": math.copysign,
    }

    _CONSTANTS: ClassVar[dict[str, float]] = {
        "pi": math.pi,
        "e": math.e,
        "tau": math.tau,
        "inf": math.inf,
    }


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": (
                "数学计算器，支持四则运算、幂运算、科学函数和数学常量。"
                "运算符: + - * / // % **（或 ^）。"
                "函数: sqrt, cbrt, exp, ln(自然对数), log(常用对数底10), log2, log10, "
                "sin, cos, tan, asin, acos, atan, sinh, cosh, tanh, "
                "degrees, radians, abs, round, floor, ceil, trunc, "
                "factorial, gcd, hypot, min, max。"
                "常量: pi, e, tau, inf。"
                "示例: '2+3*4', 'sqrt(16)', 'sin(pi/2)', 'log(e)', '2^10'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": (
                            "数学表达式，例如 '2 + 3 * 4', 'sqrt(16)', "
                            "'sin(pi/2)', 'log(e)'"
                        ),
                    },
                },
                "required": ["expression"],
            },
        },
    }
)
def calculator(expression: str) -> dict[str, Any]:
    """安全的数学计算器工具

    基于 AST 白名单求值，不使用 eval()，可防止代码注入。
    支持四则运算、幂运算、科学函数和数学常量。

    Args:
        expression: str => 数学表达式字符串

    Returns:
        dict[str, Any] => {
            "expression": 原始表达式,
            "result": 计算结果（出错时为 None）,
            "error": 错误信息（仅出错时存在）,
            "note": 备注（如无穷大提示，可选）
        }
    """
    try:
        result = _MathEvaluator.safe_evaluate(expression)
    except (ValueError, OverflowError, RecursionError) as exc:
        return {
            "expression": expression,
            "result": None,
            "error": str(exc),
        }

    # 处理特殊浮点值
    if isinstance(result, float):
        if math.isnan(result):
            return {
                "expression": expression,
                "result": None,
                "error": "计算结果为 NaN（非数字）",
            }
        if math.isinf(result):
            return {
                "expression": expression,
                "result": result,
                "note": "结果为无穷大",
            }
        # 整数值的浮点数转为 int 以保持简洁输出
        if result.is_integer():
            result = int(result)

    return {
        "expression": expression,
        "result": result,
    }
