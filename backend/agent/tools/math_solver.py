# backend/agent/tools/math_solver.py

"""符号计算工具

基于 sympy 实现微积分、方程求解、化简、展开、因式分解、
级数展开、组合数学等符号计算，适用于高等数学、线性代数、离散数学等课程。
"""

from __future__ import annotations

from typing import Any

import sympy as sp
from sympy.parsing.sympy_parser import (
    parse_expr,
    standard_transformations,
)

from backend.agent.tools.tools import tr

# 安全限制
_MAX_EXPR_LEN = 500

# 允许的符号与函数（白名单，防止任意函数调用）
_SAFE_GLOBALS: dict[str, Any] = {
    # 常量
    "pi": sp.pi,
    "E": sp.E,
    "e": sp.E,
    "I": sp.I,
    "oo": sp.oo,
    "inf": sp.oo,
    "nan": sp.nan,
    # 函数
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "asin": sp.asin,
    "acos": sp.acos,
    "atan": sp.atan,
    "sinh": sp.sinh,
    "cosh": sp.cosh,
    "tanh": sp.tanh,
    "exp": sp.exp,
    "ln": sp.log,  # 自然对数（底 e）
    "log": lambda x: sp.log(x, 10),  # 常用对数（底 10）
    "sqrt": sp.sqrt,
    "Abs": sp.Abs,
    "floor": sp.floor,
    "ceiling": sp.ceiling,
    # 构造器
    "Symbol": sp.Symbol,
    "Integer": sp.Integer,
    "Float": sp.Float,
    "Rational": sp.Rational,
}

# 支持的运算
_OPERATIONS = {
    "diff": "求导",
    "integrate": "积分",
    "limit": "求极限",
    "series": "泰勒级数展开",
    "solve": "解方程",
    "simplify": "化简",
    "expand": "展开",
    "factor": "因式分解",
    "binomial": "组合数 C(n, r)",
    "permutation": "排列数 A(n, r)",
    "summation": "求和",
}


def _safe_parse(expression: str) -> sp.Expr:
    """安全解析 sympy 表达式

    Args:
        expression: str => 数学表达式字符串

    Returns:
        sp.Expr => sympy 表达式对象

    Raises:
        ValueError: 表达式为空、过长或解析失败
    """
    expr = expression.strip()
    if not expr:
        raise ValueError("表达式不能为空")
    if len(expr) > _MAX_EXPR_LEN:
        raise ValueError(f"表达式过长（最多 {_MAX_EXPR_LEN} 字符）")
    try:
        return parse_expr(
            expr,
            transformations=standard_transformations,
            global_dict=_SAFE_GLOBALS,
            evaluate=True,
        )
    except Exception as exc:
        raise ValueError(f"表达式解析失败: {exc}") from exc


def _format_output(expr: Any) -> str:
    """格式化 sympy 输出"""
    if isinstance(expr, (list, tuple)):
        return str(expr)
    return str(expr)


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "math_solver",
            "description": (
                "符号计算工具，适用于高等数学、线性代数、离散数学等课程。"
                "支持求导、积分、极限、级数展开、解方程、化简、展开、"
                "因式分解、组合数、排列数、求和。"
                "operation 可选: diff, integrate, limit, series, solve, "
                "simplify, expand, factor, binomial, permutation, summation。"
                "示例: 求导 operation='diff' expression='x**3' variable='x'；"
                "定积分 operation='integrate' expression='x**2' variable='x' "
                "lower=0 upper=1"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": list(_OPERATIONS.keys()),
                        "description": (
                            "运算类型: diff=求导, integrate=积分, "
                            "limit=极限, series=级数, solve=解方程, "
                            "simplify=化简, expand=展开, factor=因式分解, "
                            "binomial=组合数, permutation=排列数, summation=求和"
                        ),
                    },
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，例如 'x**3 + 2*x', 'sin(x)'",
                    },
                    "variable": {
                        "type": "string",
                        "description": "运算变量，例如 'x'。diff/integrate/limit/series/solve/summation 需要",
                    },
                    "order": {
                        "type": "integer",
                        "description": "求导阶数（diff 使用），默认 1",
                        "default": 1,
                    },
                    "lower": {
                        "type": "string",
                        "description": "定积分下界或求和起点，例如 '0'。可选",
                    },
                    "upper": {
                        "type": "string",
                        "description": "定积分上界或求和终点，例如 '1'。可选",
                    },
                    "point": {
                        "type": "string",
                        "description": "极限点或级数展开点，例如 '0'。默认 '0'",
                        "default": "0",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["+", "-"],
                        "description": "极限方向: '+' 从右侧逼近, '-' 从左侧逼近。默认 '+'",
                        "default": "+",
                    },
                    "n": {
                        "type": "integer",
                        "description": "级数展开项数（series 使用），默认 6",
                        "default": 6,
                    },
                },
                "required": ["operation", "expression"],
            },
        },
    }
)
def math_solver(
    operation: str,
    expression: str,
    variable: str | None = None,
    order: int = 1,
    lower: str | None = None,
    upper: str | None = None,
    point: str = "0",
    direction: str = "+",
    n: int = 6,
) -> dict[str, Any]:
    """符号计算工具

    基于 sympy 实现微积分、方程求解等符号计算。

    Args:
        operation: str        => 运算类型
        expression: str       => 数学表达式
        variable: str | None  => 运算变量
        order: int = 1        => 求导阶数
        lower: str | None     => 积分/求和下界
        upper: str | None     => 积分/求和上界
        point: str = "0"      => 极限点/级数展开点
        direction: str = "+"  => 极限方向
        n: int = 6            => 级数展开项数

    Returns:
        dict[str, Any] => {
            "operation": 运算类型,
            "expression": 原始表达式,
            "result": 计算结果（出错时为 None）,
            "error": 错误信息（仅出错时存在）
        }
    """
    if operation not in _OPERATIONS:
        return {
            "operation": operation,
            "expression": expression,
            "result": None,
            "error": f"不支持的运算: {operation!r}，可选: {list(_OPERATIONS.keys())}",
        }

    try:
        expr = _safe_parse(expression)

        if operation == "simplify":
            result = sp.simplify(expr)

        elif operation == "expand":
            result = sp.expand(expr)

        elif operation == "factor":
            result = sp.factor(expr)

        elif operation == "binomial":
            # 组合数 C(n, r)，expression 形如 '5, 2' 或分别传入
            parts = [p.strip() for p in expression.split(",")]
            if len(parts) != 2:
                raise ValueError("组合数需要两个参数，格式 'n, r'，如 '5, 2'")
            n_val = int(_safe_parse(parts[0]))
            r_val = int(_safe_parse(parts[1]))
            result = sp.binomial(n_val, r_val)

        elif operation == "permutation":
            # 排列数 A(n, r) = n! / (n-r)!
            parts = [p.strip() for p in expression.split(",")]
            if len(parts) != 2:
                raise ValueError("排列数需要两个参数，格式 'n, r'，如 '5, 2'")
            n_val = int(_safe_parse(parts[0]))
            r_val = int(_safe_parse(parts[1]))
            result = sp.factorial(n_val) // sp.factorial(n_val - r_val)

        else:
            # 以下运算需要变量
            if not variable:
                raise ValueError(f"运算 {operation!r} 需要指定 variable 参数")
            var = sp.Symbol(variable)

            if operation == "diff":
                result = sp.diff(expr, var, order)

            elif operation == "integrate":
                if lower is not None and upper is not None:
                    # 定积分
                    lo = _safe_parse(lower)
                    hi = _safe_parse(upper)
                    result = sp.integrate(expr, (var, lo, hi))
                else:
                    # 不定积分
                    result = sp.integrate(expr, var)

            elif operation == "limit":
                pt = _safe_parse(point)
                result = sp.limit(expr, var, pt, direction)

            elif operation == "series":
                pt = _safe_parse(point)
                result = sp.series(expr, var, int(pt), n)

            elif operation == "solve":
                result = sp.solve(expr, var)

            elif operation == "summation":
                if lower is None or upper is None:
                    raise ValueError("求和需要 lower 和 upper 参数")
                lo = _safe_parse(lower)
                hi = _safe_parse(upper)
                result = sp.summation(expr, (var, lo, hi))

            else:
                raise ValueError(f"未实现的运算: {operation!r}")

        return {
            "operation": operation,
            "expression": expression,
            "result": _format_output(result),
        }

    except (ValueError, sp.SympifyError, TypeError, NotImplementedError) as exc:
        return {
            "operation": operation,
            "expression": expression,
            "result": None,
            "error": str(exc),
        }
