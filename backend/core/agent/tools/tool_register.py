# backend/core/agent/tools/tool_register.py

from typing import Any, Callable, TypeVar

ToolFn = Callable[
    ...,
    Any,
]  # 给 Tool 函数一个类型 ... 表示输入任意参数 Any 表示返回 Any

F = TypeVar(
    "F",
    bound=ToolFn,
)  # F 代表某个具体的工具函数类型（受 ToolFn 约束）


class ToolRegistry:
    def __init__(self) -> None:
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
        _, fn = self.registered_tools[name]

        try:
            return fn(**arguments)
        except Exception as e:
            return f"[Error]: {e}"
