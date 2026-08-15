# backend/agent/tools/math_tools/bitwise_calculator.py

"""位运算与布尔运算计算器工具

使用 AST 解析与白名单求值器，不使用 eval()，防止代码注入。
支持位运算、布尔运算、进制转换，适用于计算机组成、数字逻辑、密码学等课程。
"""

from __future__ import annotations

import ast
import operator
from typing import Any, ClassVar

from backend.agent.tools.math_tools._base_evaluator import BaseSafeEvaluator
from backend.agent.tools.tools import tr


def _popcount(n: int) -> int:
    """统计二进制中 1 的个数（仅支持非负整数）"""
    if n < 0:
        raise ValueError("popcount 仅支持非负整数，负数在任意精度下无确定补码表示")
    return (n).bit_count()


class _BitwiseEvaluator(BaseSafeEvaluator):
    """位运算与布尔运算 AST 求值器"""

    _BIN_OPS: ClassVar[dict[type, Any]] = {
        # 位运算
        ast.BitAnd: operator.and_,
        ast.BitOr: operator.or_,
        ast.BitXor: operator.xor,
        ast.LShift: operator.lshift,
        ast.RShift: operator.rshift,
        # 算术运算（混合表达式使用，如 0xFF + 1）
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
        ast.Invert: operator.invert,  # ~ 按位取反
        ast.Not: operator.not_,  # not 布尔取反
    }

    _FUNCTIONS: ClassVar[dict[str, Any]] = {
        "abs": abs,
        "int": int,
        "bin": bin,
        "oct": oct,
        "hex": hex,
        "bit_length": int.bit_length,
        "popcount": _popcount,
    }

    _CONSTANTS: ClassVar[dict[str, Any]] = {
        "True": True,
        "False": False,
    }

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        """处理 and / or 布尔运算"""
        values = [self.visit(v) for v in node.values]
        if isinstance(node.op, ast.And):
            result = True
            for v in values:
                result = result and v
            return result
        if isinstance(node.op, ast.Or):
            result = False
            for v in values:
                result = result or v
            return result
        raise ValueError(f"不支持的布尔运算符: {type(node.op).__name__}")


def _format_result(value: Any) -> dict[str, Any]:
    """将结果格式化为多进制表示"""
    if isinstance(value, bool):
        return {
            "decimal": int(value),
            "binary": bin(int(value)),
            "boolean": value,
        }
    if isinstance(value, int):
        result: dict[str, Any] = {
            "decimal": value,
            "binary": bin(value),
            "octal": oct(value),
            "hexadecimal": hex(value),
            "bit_length": value.bit_length(),
        }
        try:
            result["popcount"] = _popcount(value)
        except ValueError:
            result["popcount"] = None
            result["popcount_note"] = "负数不支持 popcount"
        return result
    return {"value": value}


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "bitwise_calculator",
            "description": (
                "位运算与布尔运算计算器，适用于计算机组成、数字逻辑、密码学等课程。"
                "位运算符: & | ^ ~ << >>。"
                "布尔运算符: and or not。"
                "算术运算符: + - * / // % **。"
                "函数: bin, oct, hex, int, abs, bit_length, popcount。"
                "常量: True, False。"
                "支持 0b/0o/0x 进制前缀，如 0xFF, 0b1010。"
                "示例: '0xFF & 0xAA', '0b1010 | 0b0101', '~0', '5 ^ 3', "
                "'True and False', 'bin(255)'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": (
                            "位运算表达式，例如 '0xFF & 0xAA', '0b1010 | 0b0101', "
                            "'~0', '5 ^ 3', 'True and False'"
                        ),
                    },
                },
                "required": ["expression"],
            },
        },
    }
)
def bitwise_calculator(expression: str) -> dict[str, Any]:
    """位运算与布尔运算计算器工具

    基于 AST 白名单求值，不使用 eval()，可防止代码注入。
    支持位运算、布尔运算和进制转换。

    Args:
        expression: str => 位运算表达式字符串

    Returns:
        dict[str, Any] => {
            "expression": 原始表达式,
            "result": 计算结果（出错时为 None）,
            "formats": 多进制表示（仅整数结果）,
            "error": 错误信息（仅出错时存在）
        }
    """
    try:
        result = _BitwiseEvaluator.safe_evaluate(expression)
    except (ValueError, OverflowError, RecursionError) as exc:
        return {
            "expression": expression,
            "result": None,
            "error": str(exc),
        }

    return {
        "expression": expression,
        "result": result,
        "formats": _format_result(result),
    }
