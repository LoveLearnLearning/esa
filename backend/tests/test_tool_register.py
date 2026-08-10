from backend.agent.tools.tool_register import ToolRegistry


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
