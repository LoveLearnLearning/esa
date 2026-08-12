from backend.agent.tools.tool_register import ToolRegistry
import asyncio


def _registry() -> ToolRegistry:
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
        return {"enabled": enabled, "type": type(enabled).__name__}

    return registry


def _typed_registry() -> ToolRegistry:
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
        return arguments

    return registry


def test_registry_normalizes_string_booleans_from_model_output() -> None:
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
    registry = _registry()

    assert registry.call("boolean_echo", {"enabled": "maybe"}) == (
        "[Error]: 参数 'enabled' 必须是布尔值"
    )


def test_registry_normalizes_all_declared_schema_types() -> None:
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
    registry = _typed_registry()

    assert registry.call("typed_echo", {"count": "three"}) == (
        "[Error]: 参数 'count' 必须是整数"
    )


def test_registry_awaits_async_tools() -> None:
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
        await asyncio.sleep(0)
        return {"value": value}

    assert asyncio.run(registry.acall("async_echo", {"value": "ok"})) == {
        "value": "ok"
    }
