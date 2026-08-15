"""Tests for the lifecycle-owned MCP stdio integration."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.agent.tools.bootstrap import register_builtin_tools
from backend.core.services import mcp_service
from backend.core.services.mcp_service import (
    MCPClientManager,
    MCPServerConfig,
)


class _AsyncContext:
    def __init__(self, value, events: list[str], label: str) -> None:
        self.value = value
        self.events = events
        self.label = label

    async def __aenter__(self):
        self.events.append(f"enter:{self.label}")
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        del exc_type, exc, traceback
        self.events.append(f"exit:{self.label}")


class _Block:
    def __init__(self, text: str) -> None:
        self.text = text

    def model_dump(self, **_kwargs):
        return {"type": "text", "text": self.text}


class _FakeSession:
    def __init__(self, events: list[str], tools: tuple[str, ...]) -> None:
        self.events = events
        self.tools = tools
        self.calls: list[tuple[str, dict]] = []

    async def initialize(self):
        self.events.append("initialize")
        return SimpleNamespace(protocolVersion="2025-06-18")

    async def list_tools(self):
        self.events.append("list_tools")
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name=name,
                    description="Search the web",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "count": {"type": "integer"},
                            "freshness": {
                                "type": "string",
                                "enum": ["day", "month", "year"],
                            },
                        },
                        "required": ["query"],
                    },
                )
                for name in self.tools
            ]
        )

    async def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        return SimpleNamespace(
            content=[_Block("search result")],
            structuredContent={"results": [{"title": "Result"}]},
            isError=False,
        )


def _install_fake_sdk(monkeypatch, *, tools=("you-search",)):
    events: list[str] = []
    session = _FakeSession(events, tools)

    class _Params:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    def stdio_client(_params):
        return _AsyncContext(("read", "write"), events, "transport")

    def ClientSession(_read, _write, **_kwargs):
        return _AsyncContext(session, events, "session")

    monkeypatch.setattr(
        mcp_service,
        "_load_mcp_sdk",
        lambda: (ClientSession, _Params, stdio_client),
    )
    return events, session


def _config(**overrides) -> MCPServerConfig:
    values = {
        "name": "you",
        "command": "npx",
        "args": ("--yes", "@youdotcom-oss/mcp@3.5.0"),
        "env": {"YDC_API_KEY": "secret", "YDC_ALLOWED_TOOLS": "you-search"},
        "allowed_tools": frozenset({"you-search"}),
    }
    values.update(overrides)
    return MCPServerConfig(**values)


def test_mcp_manager_starts_calls_and_stops_child_process(monkeypatch):
    events, session = _install_fake_sdk(monkeypatch)
    manager = MCPClientManager((_config(),))

    async def scenario():
        await manager.start()
        assert manager.tool_schema("you", "you-search")["required"] == ["query"]
        result = await manager.call_tool("you", "you-search", {"query": "MCP"})
        await manager.close()
        return result

    result = asyncio.run(scenario())

    assert session.calls == [("you-search", {"query": "MCP"})]
    assert result["structured_content"]["results"][0]["title"] == "Result"
    assert events == [
        "enter:transport",
        "enter:session",
        "initialize",
        "list_tools",
        "exit:session",
        "exit:transport",
    ]


def test_mcp_start_fails_closed_when_allowlisted_tool_is_missing(monkeypatch):
    events, _session = _install_fake_sdk(monkeypatch, tools=("you-contents",))
    manager = MCPClientManager((_config(),))

    with pytest.raises(RuntimeError, match="did not expose allowed tools"):
        asyncio.run(manager.start())

    assert events[-2:] == ["exit:session", "exit:transport"]


def test_mcp_tool_allowlist_rejects_unapproved_calls(monkeypatch):
    _events, _session = _install_fake_sdk(monkeypatch)
    manager = MCPClientManager((_config(),))

    async def scenario():
        await manager.start()
        try:
            with pytest.raises(PermissionError, match="not allowlisted"):
                await manager.call_tool("you", "you-research", {})
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_you_search_arguments_follow_discovered_mcp_schema():
    register_builtin_tools()
    from backend.agent.tools.web_search import build_you_search_arguments

    arguments = build_you_search_arguments(
        {
            "properties": {
                "query": {"type": "string"},
                "count": {"type": "integer"},
                "search_lang": {"type": "string"},
                "freshness": {"enum": ["day", "month", "year"]},
            }
        },
        query="  latest MCP news  ",
        max_results=50,
        language="zh-CN",
        time_range="month",
    )

    assert arguments == {
        "query": "latest MCP news",
        "count": 20,
        "search_lang": "zh-CN",
        "freshness": "month",
    }


def test_web_search_routes_through_request_bound_mcp_manager():
    register_builtin_tools()
    from backend.agent.tools.web_search import execute_web_search

    class _Manager:
        def __init__(self) -> None:
            self.call = None

        def tool_schema(self, server, tool):
            assert (server, tool) == ("you", "you-search")
            return {
                "properties": {
                    "query": {"type": "string"},
                    "count": {"type": "integer"},
                }
            }

        async def call_tool(self, server, tool, arguments):
            self.call = (server, tool, arguments)
            return {"server": server, "tool": tool, "content": []}

    manager = _Manager()
    context = SimpleNamespace(
        user_id="u1",
        conversation_id="c1",
        runtime_dependencies=SimpleNamespace(mcp_client_manager=manager),
    )
    result = asyncio.run(
        execute_web_search(context, query="Qwen news", max_results=3)
    )

    assert manager.call == (
        "you",
        "you-search",
        {"query": "Qwen news", "count": 3},
    )
    assert result["provider"] == "you.com"
    assert result["tool"] == "you-search"
