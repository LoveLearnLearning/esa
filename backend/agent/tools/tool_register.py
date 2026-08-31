# backend/agent/tools/tool_register.py

"""提供 `tool_register` 相关功能。"""


from collections.abc import Callable
import asyncio
import inspect
from typing import Any, TypeVar

from backend.core.utils.tool_arguments import normalize_tool_arguments

ToolFn = Callable[
    ...,
    Any,
]  # 给 Tool 函数一个类型 ... 表示输入任意参数 Any 表示返回 Any

F = TypeVar(
    "F",
    bound=ToolFn,
)  # F 代表某个具体的工具函数类型（受 ToolFn 约束）


class ToolRegistry:
    """封装 `ToolRegistry` 的状态与行为。"""
    def __init__(self) -> None:
        """初始化 `ToolRegistry` 实例。"""
        self.registered_tools: dict[str, tuple[dict[str, Any], ToolFn]] = {}
        # 先创建一个存 registered_tools 的字典

    def register(self, schema: dict[str, Any]) -> Callable[[F], F]:
        """
        装饰器工厂：传入 schema，返回一个真正的装饰器 deco

        Args:
            schema: dict[str, Any] => 工具函数的属性

        Returns:
            Callable[[F], F] => deco 接收什么类型的函数，就原样返回同一类型

        """

        def deco(fn: F) -> F:
            """
            decorator 函数 接受被修饰的函数 将工具函数记录到 registered_tools 字典中

            Args:
                fn: F => 传入的函数

            Returns:
                F => 返回同样类型

            """
            self.registered_tools[schema["function"]["name"]] = (schema, fn)
            return fn

        return deco

    @property
    def schemas(self) -> list[dict[str, Any]]:
        """
        所有工具的 schema，喂给 vllm

        Returns:
            list[dict[str, Any]] => 所有工具的 schema
        """
        return [schema for schema, _ in self.registered_tools.values()]

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        """
        将 tool_calls 里的 name 分发执行

        Args:
            name: str                   => tool name
            arguments: dict[str, Any]   => 调用 tools 所需要的参数

        Returns:
            Any => tools 调用后的结果
        """

        if name not in self.registered_tools:
            return f"[Error]: unknown tool {name!r}"
        schema, fn = self.registered_tools[name]

        try:
            result = fn(**self._normalize_arguments(schema, arguments))
            if inspect.isawaitable(result):
                if inspect.iscoroutine(result):
                    result.close()
                return f"[Error]: async tool {name!r} requires acall()"
            return result
        except (ValueError, TypeError, RuntimeError) as e:
            return f"[Error]: {e}"

    async def acall(self, name: str, arguments: dict[str, Any]) -> Any:
        """Execute either a synchronous or asynchronous registered tool."""

        if name not in self.registered_tools:
            return f"[Error]: unknown tool {name!r}"
        schema, fn = self.registered_tools[name]
        try:
            normalized = self._normalize_arguments(schema, arguments)
            if inspect.iscoroutinefunction(fn):
                return await fn(**normalized)
            return await asyncio.to_thread(fn, **normalized)
        except (ValueError, TypeError, RuntimeError, KeyError) as error:
            return f"[Error]: {error}"

    async def acall_strict(self, name: str, arguments: dict[str, Any]) -> Any:
        """Execute without stringifying failures at the BoundToolExecutor boundary."""

        if name not in self.registered_tools:
            raise KeyError(name)
        schema, fn = self.registered_tools[name]
        normalized = self._normalize_arguments(schema, arguments)
        if inspect.iscoroutinefunction(fn):
            return await fn(**normalized)
        return await asyncio.to_thread(fn, **normalized)

    @staticmethod
    def _normalize_arguments(
        schema: dict[str, Any], arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """按工具 Schema 归一全部参数类型，作为执行前最后的边界保护。"""
        return normalize_tool_arguments(schema, arguments)
