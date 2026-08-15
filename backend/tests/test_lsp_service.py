# backend/tests/test_lsp_service.py

"""验证 `lsp_service` 相关行为与回归场景。"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.core.services.lsp_service import LspService
from backend.core.utils.models import SessionPrincipal
from backend.core.web.routers import lsp


_FAKE_SERVER = r'''
import json
import sys

while True:
    content_length = None
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            raise SystemExit(0)
        if line in {b"\r\n", b"\n"}:
            break
        name, value = line.decode("ascii").split(":", 1)
        if name.lower() == "content-length":
            content_length = int(value.strip())
    message = json.loads(sys.stdin.buffer.read(content_length))
    if "id" not in message:
        continue
    response = {
        "jsonrpc": "2.0",
        "id": message["id"],
        "result": {
            "capabilities": {"completionProvider": {"triggerCharacters": ["."]}},
            "echo_method": message.get("method"),
        },
    }
    payload = json.dumps(response).encode("utf-8")
    sys.stdout.buffer.write(
        f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload
    )
    sys.stdout.buffer.flush()
'''


def _service(tmp_path) -> LspService:
    """处理 `_service` 相关逻辑。"""
    server = tmp_path / "fake_lsp.py"
    server.write_text(_FAKE_SERVER, encoding="utf-8")
    return LspService(
        commands={"cpp": (sys.executable, "-u", str(server))},
        filenames={"cpp": "main.cpp"},
        max_sessions=2,
        max_sessions_per_user=1,
    )


def test_stdio_bridge_frames_json_rpc(tmp_path) -> None:
    """验证 `stdio_bridge_frames_json_rpc` 场景。"""
    async def run() -> None:
        """执行 `run` 相关数据。"""
        service = _service(tmp_path)
        async with service.open(user_id="user-1", language="cpp") as bridge:
            assert bridge.document_uri.endswith("/main.cpp")
            await bridge.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 7,
                        "method": "initialize",
                        "params": {},
                    }
                )
            )
            response = json.loads(await bridge.receive())
            assert response["id"] == 7
            assert response["result"]["echo_method"] == "initialize"

    asyncio.run(run())


@pytest.mark.skipif(shutil.which("clangd") is None, reason="clangd not installed")
def test_real_clangd_returns_cpp_symbols() -> None:
    """验证 `real_clangd_returns_cpp_symbols` 场景。"""
    async def receive_response(bridge, request_id: int) -> dict:
        """处理 `receive_response` 相关逻辑。

        Args:
            bridge: object => `bridge` 参数。
            request_id: int => request ID。

        Returns:
            dict => 处理结果。
        """
        while True:
            message = json.loads(await asyncio.wait_for(bridge.receive(), timeout=10))
            if message.get("id") == request_id:
                return message

    async def run() -> None:
        """执行 `run` 相关数据。"""
        service = LspService(
            commands={"cpp": ("clangd",)},
            filenames={"cpp": "main.cpp"},
            max_sessions=1,
            max_sessions_per_user=1,
        )
        async with service.open(user_id="user-1", language="cpp") as bridge:
            await bridge.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "processId": None,
                            "rootUri": bridge.root_uri,
                            "capabilities": {},
                        },
                    }
                )
            )
            initialize = await receive_response(bridge, 1)
            assert "completionProvider" in initialize["result"]["capabilities"]
            await bridge.send(
                json.dumps({"jsonrpc": "2.0", "method": "initialized", "params": {}})
            )
            source = (
                "struct ListNode {};\n"
                "int main() {\n"
                "  ListNode* currentNode = nullptr;\n"
                "  currentN\n"
                "}\n"
            )
            await bridge.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "textDocument/didOpen",
                        "params": {
                            "textDocument": {
                                "uri": bridge.document_uri,
                                "languageId": "cpp",
                                "version": 1,
                                "text": source,
                            }
                        },
                    }
                )
            )
            await bridge.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "textDocument/completion",
                        "params": {
                            "textDocument": {"uri": bridge.document_uri},
                            "position": {"line": 3, "character": 10},
                        },
                    }
                )
            )
            completion = await receive_response(bridge, 2)
            result = completion["result"]
            items = result if isinstance(result, list) else result["items"]
            labels = [item["label"] for item in items]
            assert any(label.strip() == "currentNode" for label in labels), labels[:40]

            await bridge.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "shutdown",
                        "params": None,
                    }
                )
            )
            await receive_response(bridge, 3)
            await bridge.send(
                json.dumps({"jsonrpc": "2.0", "method": "exit", "params": None})
            )

    asyncio.run(run())


class _SessionStore:
    """封装 `session store` 数据持久化操作。"""
    def __init__(self, session: SessionPrincipal) -> None:
        """初始化 `_SessionStore` 实例。"""
        self.session = session

    def get(self, token: str) -> SessionPrincipal | None:
        """获取 `get` 相关数据。"""
        return self.session if token == "valid-token" else None


def test_authenticated_websocket_proxies_lsp(tmp_path) -> None:
    """验证 `authenticated_websocket_proxies_lsp` 场景。"""
    app = FastAPI()
    app.state.lsp_allowed_origins = ("https://www.example.test",)
    app.state.lsp_service = _service(tmp_path)
    app.state.session_store = _SessionStore(
        SessionPrincipal(
            session_id="valid-token",
            user_id="user-1",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
    )
    app.include_router(lsp.router)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/lsp/cpp",
            headers={"origin": "https://www.example.test"},
        ) as websocket:
            websocket.send_json({"type": "esa/auth", "token": "valid-token"})
            ready = websocket.receive_json()
            assert ready["type"] == "esa/lsp-ready"
            assert ready["document_uri"].endswith("/main.cpp")

            websocket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {},
                }
            )
            response = websocket.receive_json()
            assert response["id"] == 1
            assert response["result"]["echo_method"] == "initialize"


def test_websocket_rejects_invalid_session(tmp_path) -> None:
    """验证 `websocket_rejects_invalid_session` 场景。"""
    app = FastAPI()
    app.state.lsp_allowed_origins = ("https://www.example.test",)
    app.state.lsp_service = _service(tmp_path)
    app.state.session_store = _SessionStore(
        SessionPrincipal(
            session_id="valid-token",
            user_id="user-1",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
    )
    app.include_router(lsp.router)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/lsp/cpp",
            headers={"origin": "https://www.example.test"},
        ) as websocket:
            websocket.send_json({"type": "esa/auth", "token": "bad-token"})
            error = websocket.receive_json()
            assert error == {
                "type": "esa/lsp-error",
                "detail": "登录会话已失效",
            }
