# backend/core/agent/tools/tool_register.py


from collections.abc import Callable
from typing import Any, TypeVar

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
        schema, fn = self.registered_tools[name]

        try:
            return fn(**self._normalize_arguments(schema, arguments))
        except (ValueError, TypeError, RuntimeError) as e:
            return f"[Error]: {e}"

    @staticmethod
    def _normalize_arguments(
        schema: dict[str, Any], arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """按工具 schema 归一化模型偶发的字符串布尔值。

        模型通常输出 JSON ``true/false``，但也可能输出
        ``True/False`` 或带引号的 ``"True"``。该边界是调用工具前
        最后的类型保护，避免字符串流入 SQLite 层后触发 ``int("True")``。
        """
        properties = (
            schema.get("function", {}).get("parameters", {}).get("properties", {})
        )
        normalized = dict(arguments)
        for key, value in arguments.items():
            specification = properties.get(key, {})
            if specification.get("type") != "boolean" or value is None:
                continue
            if isinstance(value, bool):
                continue
            if isinstance(value, int) and value in (0, 1):
                normalized[key] = bool(value)
                continue
            if isinstance(value, str):
                candidate = value.strip().casefold()
                if candidate in {"true", "1"}:
                    normalized[key] = True
                    continue
                if candidate in {"false", "0"}:
                    normalized[key] = False
                    continue
            raise ValueError(f"参数 {key!r} 必须是布尔值")
        return normalized
