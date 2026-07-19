# backend/agent/tools/calculator.py

"""安全的数学计算器工具

使用 AST 解析与白名单求值器，不使用 eval()，防止代码注入。
支持四则运算、幂运算、科学函数和数学常量。
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from backend.agent.tools.tools import tr

# 安全限制：防止超长表达式造成 DoS
_MAX_EXPR_LEN = 1000

# 兼容 Python 3.10（math.cbrt 自 3.11 起存在）
try:
    _cbrt = math.cbrt  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover

    def _cbrt(x: float) -> float:
        return math.copysign(abs(x) ** (1.0 / 3.0), x)


# 支持的二元运算符
_BIN_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

# 支持的一元运算符
_UNARY_OPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# 支持的数学函数
_FUNCTIONS: dict[str, Any] = {
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

# 支持的数学常量
_CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "inf": math.inf,
}


class _SafeCalculator(ast.NodeVisitor):
    """基于白名单的 AST 安全求值器。

    仅允许数值常量、预定义常量、白名单运算符与函数调用，
    任何其他 AST 节点（属性访问、下标、赋值、lambda 等）均被拒绝。
    """

    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"不支持的常量类型: {type(node.value).__name__}")

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise ValueError(f"未知的变量或常量: {node.id!r}")

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        left = self.visit(node.left)
        right = self.visit(node.right)
        op_type = type(node.op)
        if op_type not in _BIN_OPS:
            raise ValueError(f"不支持的二元运算符: {op_type.__name__}")
        try:
            return _BIN_OPS[op_type](left, right)
        except ZeroDivisionError:
            raise ValueError("除零错误") from None
        except (TypeError, ValueError) as exc:
            raise ValueError(f"运算错误: {exc}") from exc

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self.visit(node.operand)
        op_type = type(node.op)
        if op_type not in _UNARY_OPS:
            raise ValueError(f"不支持的一元运算符: {op_type.__name__}")
        return _UNARY_OPS[op_type](operand)

    def visit_Call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):
            raise ValueError("仅支持简单函数调用")
        fn_name = node.func.id
        if fn_name not in _FUNCTIONS:
            raise ValueError(f"未知的函数: {fn_name!r}")
        if node.keywords:
            raise ValueError("不支持关键字参数")
        args = [self.visit(arg) for arg in node.args]
        try:
            return _FUNCTIONS[fn_name](*args)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"函数 '{fn_name}' 调用错误: {exc}") from exc

    def generic_visit(self, node: ast.AST) -> Any:
        raise ValueError(f"不支持的表达式类型: {type(node).__name__}")


def _safe_evaluate(expression: str) -> float | int:
    """安全求值数学表达式

    Args:
        expression: str => 数学表达式字符串

    Returns:
        float | int => 计算结果

    Raises:
        ValueError: 表达式为空、过长、语法错误或包含不支持的内容
    """
    expr = expression.strip()
    if not expr:
        raise ValueError("表达式不能为空")
    if len(expr) > _MAX_EXPR_LEN:
        raise ValueError(f"表达式过长（最多 {_MAX_EXPR_LEN} 字符）")

    # 将 ^ 转换为 ** 以符合数学惯用写法
    expr = expr.replace("^", "**")

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"语法错误: {exc.msg}") from exc

    return _SafeCalculator().visit(tree)


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
        result = _safe_evaluate(expression)
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
