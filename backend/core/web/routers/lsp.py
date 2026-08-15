# backend/core/web/routers/lsp.py

"""提供 `lsp` 相关功能。"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core.services.lsp_service import (
    LanguageServerUnavailable,
    LspProtocolError,
    LspService,
    LspSessionLimitExceeded,
)
from backend.core.stores.session_store import SessionStore
from backend.core.utils.config import LSP_AUTH_TIMEOUT_SECONDS

router = APIRouter(prefix="/lsp", tags=["lsp"])
logger = logging.getLogger(__name__)


async def _reject(websocket: WebSocket, detail: str, *, code: int = 1008) -> None:
    """处理 `_reject` 相关逻辑。"""
    with suppress(RuntimeError):
        await websocket.send_json({"type": "esa/lsp-error", "detail": detail})
    with suppress(RuntimeError):
        await websocket.close(code=code, reason=detail[:120])


def _authenticate(websocket: WebSocket, token: str):
    """处理 `_authenticate` 相关逻辑。"""
    session_store: SessionStore = websocket.app.state.session_store
    session = session_store.get(token)
    if session is None or session.expires_at <= datetime.now(timezone.utc):
        return None
    return session


@router.websocket("/{language}")
async def language_server_socket(websocket: WebSocket, language: str) -> None:
    """处理 `language_server_socket` 相关逻辑。

    Args:
        websocket: WebSocket => `websocket` 参数。
        language: str => `language` 参数。
    """
    language = language.strip().lower()
    allowed_origins = getattr(websocket.app.state, "lsp_allowed_origins", ())
    origin = websocket.headers.get("origin")
    if origin and origin not in allowed_origins:
        await websocket.close(code=1008, reason="origin not allowed")
        return

    await websocket.accept()
    service = getattr(websocket.app.state, "lsp_service", None)
    if not isinstance(service, LspService) or not service.supports(language):
        await _reject(websocket, "该语言的 LSP 未启用", code=1013)
        return

    try:
        auth_text = await asyncio.wait_for(
            websocket.receive_text(), timeout=LSP_AUTH_TIMEOUT_SECONDS
        )
        auth_message = json.loads(auth_text)
    except (asyncio.TimeoutError, WebSocketDisconnect, json.JSONDecodeError):
        await _reject(websocket, "LSP 认证失败")
        return
    if not isinstance(auth_message, dict) or auth_message.get("type") != "esa/auth":
        await _reject(websocket, "LSP 认证消息无效")
        return
    token = auth_message.get("token")
    if not isinstance(token, str) or not token:
        await _reject(websocket, "LSP 认证消息无效")
        return
    session = _authenticate(websocket, token)
    if session is None:
        await _reject(websocket, "登录会话已失效")
        return

    try:
        async with service.open(user_id=session.user_id, language=language) as bridge:
            await websocket.send_json(
                {
                    "type": "esa/lsp-ready",
                    "language": language,
                    "root_uri": bridge.root_uri,
                    "document_uri": bridge.document_uri,
                }
            )

            async def client_to_server() -> None:
                """处理 `client_to_server` 相关逻辑。"""
                while True:
                    await bridge.send(await websocket.receive_text())

            async def server_to_client() -> None:
                """处理 `server_to_client` 相关逻辑。"""
                while True:
                    await websocket.send_text(await bridge.receive())

            tasks = {
                asyncio.create_task(client_to_server()),
                asyncio.create_task(server_to_client()),
            }
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            for task in pending:
                with suppress(asyncio.CancelledError):
                    await task
            for task in done:
                task.result()
    except WebSocketDisconnect:
        pass
    except LanguageServerUnavailable:
        await _reject(websocket, "语言服务器未安装或启动失败", code=1013)
    except LspSessionLimitExceeded:
        await _reject(websocket, "语言服务器连接数已满", code=1013)
    except (LspProtocolError, EOFError, asyncio.IncompleteReadError):
        logger.warning("LSP[%s] protocol failed", language, exc_info=True)
        await _reject(websocket, "语言服务器连接异常", code=1011)
    except Exception:
        logger.exception("LSP[%s] websocket failed", language)
        await _reject(websocket, "语言服务器内部错误", code=1011)
