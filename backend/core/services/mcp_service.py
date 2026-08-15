"""Lifecycle-managed clients for local stdio MCP server processes."""

from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Mapping

from backend.core.log.logger import get_pipeline_logger


logger = get_pipeline_logger("MCP", __name__)


def _load_mcp_sdk() -> tuple[Any, Any, Any]:
    """Import the optional SDK only when an enabled MCP server is started."""

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as error:  # pragma: no cover - deployment configuration
        raise RuntimeError(
            "MCP Python SDK is not installed; install requirements.txt"
        ) from error
    return ClientSession, StdioServerParameters, stdio_client


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    """Configuration for one child-process MCP server."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    allowed_tools: frozenset[str] = frozenset()
    startup_timeout_seconds: float = 30.0
    call_timeout_seconds: float = 30.0
    max_result_chars: int = 120_000

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.command.strip():
            raise ValueError("MCP server name and command are required")
        if not self.allowed_tools:
            raise ValueError("MCP server must declare an explicit tool allowlist")
        if self.startup_timeout_seconds <= 0 or self.call_timeout_seconds <= 0:
            raise ValueError("MCP timeouts must be positive")
        if self.max_result_chars < 1:
            raise ValueError("MCP max_result_chars must be positive")


class MCPStdioServer:
    """Own one MCP stdio subprocess and its initialized client session."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._stack: AsyncExitStack | None = None
        self._session: Any | None = None
        self._tools: dict[str, dict[str, Any]] = {}
        self._call_semaphore = asyncio.Semaphore(4)

    @property
    def ready(self) -> bool:
        return self._session is not None

    @property
    def tools(self) -> Mapping[str, dict[str, Any]]:
        return dict(self._tools)

    async def start(self) -> None:
        """Spawn the process, complete MCP initialization, and verify tools."""

        if self.ready:
            return
        ClientSession, StdioServerParameters, stdio_client = _load_mcp_sdk()
        stack = AsyncExitStack()
        try:
            params = StdioServerParameters(
                command=self.config.command,
                args=list(self.config.args),
                env=dict(self.config.env),
            )
            # These context managers own AnyIO cancel scopes. Enter and exit them
            # in the FastAPI lifespan task rather than inside asyncio.wait_for.
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(params)
            )
            session = await stack.enter_async_context(
                ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(
                        seconds=self.config.call_timeout_seconds
                    ),
                )
            )
            initialized = await asyncio.wait_for(
                session.initialize(),
                timeout=self.config.startup_timeout_seconds,
            )
            listed = await asyncio.wait_for(
                session.list_tools(),
                timeout=self.config.startup_timeout_seconds,
            )
            discovered = {
                tool.name: {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": dict(tool.inputSchema),
                }
                for tool in listed.tools
            }
            missing = sorted(self.config.allowed_tools - discovered.keys())
            if missing:
                raise RuntimeError(
                    f"MCP server {self.config.name!r} did not expose allowed tools: "
                    f"{', '.join(missing)}"
                )
            self._stack = stack
            self._session = session
            self._tools = {
                name: discovered[name] for name in sorted(self.config.allowed_tools)
            }
            logger.info(
                "server started server=%s protocol=%s tools=%s command=%s",
                self.config.name,
                initialized.protocolVersion,
                ",".join(self._tools),
                self.config.command,
            )
        except BaseException:
            await stack.aclose()
            raise

    async def close(self) -> None:
        """Close the MCP session and terminate its complete child process tree."""

        stack = self._stack
        self._stack = None
        self._session = None
        self._tools = {}
        if stack is None:
            return
        try:
            await stack.aclose()
        finally:
            logger.info("server stopped server=%s", self.config.name)

    def tool_schema(self, name: str) -> dict[str, Any]:
        try:
            return dict(self._tools[name]["input_schema"])
        except KeyError as error:
            raise RuntimeError(
                f"MCP tool {self.config.name}/{name} is not available"
            ) from error

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Call one allowlisted MCP tool and return JSON-safe content."""

        if name not in self.config.allowed_tools:
            raise PermissionError(
                f"MCP tool {self.config.name}/{name} is not allowlisted"
            )
        session = self._session
        if session is None:
            raise RuntimeError(f"MCP server {self.config.name!r} is not running")

        logger.info(
            "tool call started server=%s tool=%s argument_keys=%s",
            self.config.name,
            name,
            ",".join(sorted(arguments)),
        )
        started = asyncio.get_running_loop().time()
        try:
            async with self._call_semaphore:
                result = await asyncio.wait_for(
                    session.call_tool(name, arguments=dict(arguments)),
                    timeout=self.config.call_timeout_seconds,
                )
        except asyncio.TimeoutError as error:
            logger.warning(
                "tool call timed out server=%s tool=%s timeout_seconds=%.2f",
                self.config.name,
                name,
                self.config.call_timeout_seconds,
            )
            raise RuntimeError(f"MCP tool {name!r} timed out") from error
        except Exception as error:
            logger.exception(
                "tool call failed server=%s tool=%s", self.config.name, name
            )
            raise RuntimeError(f"MCP tool {name!r} failed: {error}") from error

        payload = self._result_payload(name, result)
        logger.info(
            "tool call finished server=%s tool=%s latency_ms=%.2f result_chars=%s",
            self.config.name,
            name,
            (asyncio.get_running_loop().time() - started) * 1000,
            len(json.dumps(payload, ensure_ascii=False, default=str)),
        )
        return payload

    def _result_payload(self, name: str, result: Any) -> dict[str, Any]:
        blocks = []
        for item in result.content:
            if hasattr(item, "model_dump"):
                blocks.append(item.model_dump(mode="json", by_alias=True))
            else:  # pragma: no cover - compatibility with future SDK blocks
                blocks.append(str(item))
        payload: dict[str, Any] = {
            "server": self.config.name,
            "tool": name,
            "content": blocks,
        }
        if result.structuredContent is not None:
            payload["structured_content"] = result.structuredContent
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        if result.isError:
            raise RuntimeError(f"MCP tool {name!r} returned an error: {serialized}")
        if len(serialized) > self.config.max_result_chars:
            return {
                "server": self.config.name,
                "tool": name,
                "truncated": True,
                "content": serialized[: self.config.max_result_chars],
            }
        return payload


class MCPClientManager:
    """Start, route, and stop a fixed set of local MCP child processes."""

    def __init__(self, configs: tuple[MCPServerConfig, ...]) -> None:
        names = [config.name for config in configs]
        if len(names) != len(set(names)):
            raise ValueError("MCP server names must be unique")
        self._servers = {
            config.name: MCPStdioServer(config) for config in configs
        }

    async def start(self) -> None:
        started: list[MCPStdioServer] = []
        try:
            for server in self._servers.values():
                await server.start()
                started.append(server)
        except BaseException:
            for server in reversed(started):
                await server.close()
            raise

    async def close(self) -> None:
        for server in reversed(tuple(self._servers.values())):
            try:
                await server.close()
            except Exception:
                logger.exception(
                    "failed to stop server server=%s", server.config.name
                )

    def tool_schema(self, server: str, tool: str) -> dict[str, Any]:
        return self._get_server(server).tool_schema(tool)

    async def call_tool(
        self,
        server: str,
        tool: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        return await self._get_server(server).call_tool(tool, arguments)

    def _get_server(self, name: str) -> MCPStdioServer:
        try:
            return self._servers[name]
        except KeyError as error:
            raise RuntimeError(f"unknown MCP server {name!r}") from error
