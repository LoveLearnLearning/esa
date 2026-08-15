# backend/tests/test_tool_register.py

"""验证 `tool_register` 相关行为与回归场景。"""

from backend.agent.tools.tool_register import ToolRegistry
import asyncio


def _registry() -> ToolRegistry:
    """处理 `_registry` 相关逻辑。"""
    registry = ToolRegistry()

    @registry.register(
        {
            "type": "function",
            "function": {
                "name": "boolean_echo",
                "parameters": {
                    "type": "object",
                    "properties": {"enabled": {"type": "boolean"}},
                    "required": ["enabled"],
                },
            },
        }
    )
    def boolean_echo(enabled: bool) -> dict:
        """处理 `boolean_echo` 相关逻辑。"""
        return {"enabled": enabled, "type": type(enabled).__name__}

    return registry


def _typed_registry() -> ToolRegistry:
    """处理 `_typed_registry` 相关逻辑。"""
    registry = ToolRegistry()

    @registry.register(
        {
            "type": "function",
            "function": {
                "name": "typed_echo",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lower": {"type": "string"},
                        "count": {"type": "integer"},
                        "ratio": {"type": "number"},
                        "enabled": {"type": "boolean"},
                        "items": {"type": "array"},
                        "config": {"type": "object"},
                    },
                },
            },
        }
    )
    def typed_echo(**arguments: object) -> dict:
        """处理 `typed_echo` 相关逻辑。"""
        return arguments

    return registry


def test_registry_normalizes_string_booleans_from_model_output() -> None:
    """验证 `registry_normalizes_string_booleans_from_model_output` 场景。"""
    registry = _registry()

    assert registry.call("boolean_echo", {"enabled": "True"}) == {
        "enabled": True,
        "type": "bool",
    }
    assert registry.call("boolean_echo", {"enabled": "false"}) == {
        "enabled": False,
        "type": "bool",
    }


def test_registry_rejects_invalid_boolean_literal_with_clear_error() -> None:
    """验证 `registry_rejects_invalid_boolean_literal_with_clear_error` 场景。"""
    registry = _registry()

    assert registry.call("boolean_echo", {"enabled": "maybe"}) == (
        "[Error]: 参数 'enabled' 必须是布尔值"
    )


def test_registry_normalizes_all_declared_schema_types() -> None:
    """验证 `registry_normalizes_all_declared_schema_types` 场景。"""
    registry = _typed_registry()

    assert registry.call(
        "typed_echo",
        {
            "lower": 0,
            "count": "3",
            "ratio": "0.5",
            "enabled": "True",
            "items": '["a", "b"]',
            "config": '{"source": "model"}',
        },
    ) == {
        "lower": "0",
        "count": 3,
        "ratio": 0.5,
        "enabled": True,
        "items": ["a", "b"],
        "config": {"source": "model"},
    }


def test_registry_rejects_invalid_integer_with_clear_error() -> None:
    """验证 `registry_rejects_invalid_integer_with_clear_error` 场景。"""
    registry = _typed_registry()

    assert registry.call("typed_echo", {"count": "three"}) == (
        "[Error]: 参数 'count' 必须是整数"
    )


def test_registry_awaits_async_tools() -> None:
    """验证 `registry_awaits_async_tools` 场景。"""
    registry = ToolRegistry()

    @registry.register(
        {
            "type": "function",
            "function": {
                "name": "async_echo",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            },
        }
    )
    async def async_echo(value: str) -> dict:
        """处理 `async_echo` 相关逻辑。"""
        await asyncio.sleep(0)
        return {"value": value}

    assert asyncio.run(registry.acall("async_echo", {"value": "ok"})) == {
        "value": "ok"
    }
