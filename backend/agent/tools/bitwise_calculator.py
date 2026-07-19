# backend/agent/tools/bitwise_calculator.py

"""位运算与布尔运算计算器工具

使用 AST 解析与白名单求值器，不使用 eval()，防止代码注入。
支持位运算、布尔运算、进制转换，适用于计算机组成、数字逻辑、密码学等课程。
"""

from __future__ import annotations

import ast
import operator
from typing import Any

from backend.agent.tools.tools import tr

# 安全限制：防止超长表达式造成 DoS
_MAX_EXPR_LEN = 1000


def _popcount(n: int) -> int:
    """统计二进制中 1 的个数（仅支持非负整数）"""
    if n < 0:
        raise ValueError("popcount 仅支持非负整数，负数在任意精度下无确定补码表示")
    return bin(n).count("1")


# 支持的二元运算符（含位运算与算术运算，便于混合表达式）
_BIN_OPS: dict[type, Any] = {
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

# 支持的一元运算符
_UNARY_OPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Invert: operator.invert,  # ~ 按位取反
    ast.Not: operator.not_,  # not 布尔取反
}

# 支持的函数
_FUNCTIONS: dict[str, Any] = {
    "abs": abs,
    "int": int,
    "bin": bin,
    "oct": oct,
    "hex": hex,
    "bit_length": int.bit_length,
    "popcount": _popcount,
}

# 支持的常量
_CONSTANTS: dict[str, Any] = {
    "True": True,
    "False": False,
}


class _SafeBitwiseEvaluator(ast.NodeVisitor):
    """基于白名单的 AST 安全求值器。

    仅允许整数值常量、布尔常量、白名单运算符与函数调用，
    任何其他 AST 节点（属性访问、下标、赋值、lambda 等）均被拒绝。
    """

    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        if isinstance(node.value, (int, float, bool)):
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


def _safe_evaluate(expression: str) -> Any:
    """安全求值位运算表达式

    Args:
        expression: str => 位运算表达式字符串

    Returns:
        Any => 计算结果（int 或 bool）

    Raises:
        ValueError: 表达式为空、过长、语法错误或包含不支持的内容
    """
    expr = expression.strip()
    if not expr:
        raise ValueError("表达式不能为空")
    if len(expr) > _MAX_EXPR_LEN:
        raise ValueError(f"表达式过长（最多 {_MAX_EXPR_LEN} 字符）")

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"语法错误: {exc.msg}") from exc

    return _SafeBitwiseEvaluator().visit(tree)


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
        result = _safe_evaluate(expression)
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
