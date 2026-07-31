"""AST 安全求值器基类

提供基于白名单的 AST 安全求值通用框架，子类只需配置白名单常量即可。
不使用 eval()，防止代码注入。
"""

from __future__ import annotations

import ast
from typing import Any, ClassVar


class BaseSafeEvaluator(ast.NodeVisitor):
    """基于白名单的 AST 安全求值器基类。

    子类通过覆写以下类属性来配置白名单：
        _BIN_OPS:  支持的二元运算符 {AST节点类型: 运算函数}
        _UNARY_OPS:支持的一元运算符 {AST节点类型: 运算函数}
        _FUNCTIONS:支持的函数名 {名称: 可调用对象}
        _CONSTANTS:支持的常量名 {名称: 值}
        _REPLACE_CARET: 是否将 ^ 替换为 **（数学计算器需要，位运算不需要）

    仅允许白名单内的运算，任何其他 AST 节点均被拒绝。
    """

    # 安全限制：防止超长表达式造成 DoS
    _MAX_EXPR_LEN: ClassVar[int] = 1000

    # 白名单（子类覆写）
    _BIN_OPS: ClassVar[dict[type, Any]] = {}
    _UNARY_OPS: ClassVar[dict[type, Any]] = {}
    _FUNCTIONS: ClassVar[dict[str, Any]] = {}
    _CONSTANTS: ClassVar[dict[str, Any]] = {}

    # 是否将 ^ 替换为 **（数学计算器需要，位运算不需要）
    _REPLACE_CARET: ClassVar[bool] = False

    # ------------------------------------------------------------------
    # AST 节点访问方法
    # ------------------------------------------------------------------

    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"不支持的常量类型: {type(node.value).__name__}")

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id in self._CONSTANTS:
            return self._CONSTANTS[node.id]
        raise ValueError(f"未知的变量或常量: {node.id!r}")

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        left = self.visit(node.left)
        right = self.visit(node.right)
        op_type = type(node.op)
        if op_type not in self._BIN_OPS:
            raise ValueError(f"不支持的二元运算符: {op_type.__name__}")
        try:
            return self._BIN_OPS[op_type](left, right)
        except ZeroDivisionError:
            raise ValueError("除零错误") from None
        except (TypeError, ValueError) as exc:
            raise ValueError(f"运算错误: {exc}") from exc

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self.visit(node.operand)
        op_type = type(node.op)
        if op_type not in self._UNARY_OPS:
            raise ValueError(f"不支持的一元运算符: {op_type.__name__}")
        return self._UNARY_OPS[op_type](operand)

    def visit_Call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):
            raise TypeError("仅支持简单函数调用")
        fn_name = node.func.id
        if fn_name not in self._FUNCTIONS:
            raise ValueError(f"未知的函数: {fn_name!r}")
        if node.keywords:
            raise ValueError("不支持关键字参数")
        args = [self.visit(arg) for arg in node.args]
        try:
            return self._FUNCTIONS[fn_name](*args)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"函数 '{fn_name}' 调用错误: {exc}") from exc

    def generic_visit(self, node: ast.AST) -> Any:
        raise ValueError(f"不支持的表达式类型: {type(node).__name__}")

    # ------------------------------------------------------------------
    # 入口方法
    # ------------------------------------------------------------------

    @classmethod
    def safe_evaluate(cls, expression: str) -> Any:
        """安全求值表达式

        Args:
            expression: 表达式字符串

        Returns:
            计算结果

        Raises:
            ValueError: 表达式为空、过长、语法错误或包含不支持的内容
        """
        expr = expression.strip()
        if not expr:
            raise ValueError("表达式不能为空")
        if len(expr) > cls._MAX_EXPR_LEN:
            raise ValueError(f"表达式过长（最多 {cls._MAX_EXPR_LEN} 字符）")

        if cls._REPLACE_CARET:
            expr = expr.replace("^", "**")

        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"语法错误: {exc.msg}") from exc

        return cls().visit(tree)