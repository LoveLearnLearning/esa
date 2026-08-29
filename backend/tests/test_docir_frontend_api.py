# backend/tests/test_docir_frontend_api.py

"""验证 `docir_frontend_api` 相关行为与回归场景。"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from backend.agent.mm import AttachmentPreparationStatus
from backend.core.stores.chat_store import ChatStore
from backend.core.stores.group_store import GroupStore
from backend.core.stores.migrations import run_migrations
from backend.core.stores.user_store import UserStore
from backend.core.services.user_attachment_service import UserAttachmentStore
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.concurrency import ConversationTurnCoordinator
from backend.core.web.deps import get_current_session
from backend.core.web.routers import chat
from backend.core.web.schemas import SendMessageRequest


class _ASGIClient:
    """Thread-free HTTP client for restricted test executors."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        async def send() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url="http://testserver",
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(send())

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)


class _ProfileBuilder:
    """封装 `_ProfileBuilder` 的状态与行为。"""
    def build(self, query):
        """构建 `build` 相关数据。"""
        return None


class _MMSessions:
    """封装 `_MMSessions` 的状态与行为。"""
    def __init__(self, conversation_id):
        """初始化 `_MMSessions` 实例。"""
        self.conversation_id = conversation_id
        self.prepare_calls = 0
        self._status = {}

    def register_stored(self, session_id, attachment_id):
        self._status[(session_id, attachment_id)] = AttachmentPreparationStatus(
            attachment_id=attachment_id
        )

    async def start_prepare(self, session_id, attachment_id, path):
        self.prepare_calls += 1
        self._status[(session_id, attachment_id)] = AttachmentPreparationStatus(
            attachment_id=attachment_id,
            state="ready",
            document_id="doc-1",
            mode="direct",
            token_count=32,
            page_count=2,
            element_count=2,
            visual_asset_count=1,
        )
        return self._status[(session_id, attachment_id)]

    def status(self, session_id, attachment_id):
        return self._status.get(
            (session_id, attachment_id),
            AttachmentPreparationStatus(attachment_id=attachment_id),
        )

    async def prepare(self, session_id, paths):
        """准备 `prepare` 相关数据。

        Args:
            session_id: object => 会话 ID。
            paths: object => `paths` 参数。

        Returns:
            object => 处理结果。
        """
        self.prepare_calls += 1
        source = Path(paths[0])
        assert source.name == "notes.pdf"
        assert source.read_bytes() == b"pdf-content"
        document = SimpleNamespace(
            document_id="doc-1",
            source=SimpleNamespace(
                filename=source.name,
            ),
            elements=(object(), object()),
            source_page_count=2,
            parsed_page_count=2,
            validation=SimpleNamespace(status=SimpleNamespace(value="passed")),
            quality_issues=(),
        )
        return (
            SimpleNamespace(
                document=document,
                mode=SimpleNamespace(value="direct"),
                token_count=32,
            ),
        )

    def context_for(self, session_id, attachment_id, query):
        """处理 `context_for` 相关逻辑。

        Args:
            session_id: object => 会话 ID。
            attachment_id: object => 附件 ID。
            query: object => 查询文本。

        Returns:
            object => 处理结果。
        """
        if session_id != self.conversation_id or attachment_id != "doc-1":
            raise KeyError(attachment_id)
        return self.context

    async def remove(self, session_id, attachment_id):
        """移除 `remove` 相关数据。

        Args:
            session_id: object => 会话 ID。
            attachment_id: object => 附件 ID。

        Returns:
            object => 处理结果。
        """
        return attachment_id == "doc-1"

    async def clear(self, session_id):
        """清空 `clear` 相关数据。"""
        return None


class _Agent:
    """封装 `_Agent` 的状态与行为。"""
    def __init__(self):
        """初始化 `_Agent` 实例。"""
        self.run_spec = None

    async def run(self, run_spec):
        """执行 `run` 相关数据。"""
        self.run_spec = run_spec
        content = run_spec.messages[-1]["content"]
        return [
            {"role": "user", "content": content, "is_visible": True},
            {"role": "assistant", "content": "done", "is_visible": True},
        ]


def _state(tmp_path):
    """处理 `_state` 相关逻辑。"""
    database = tmp_path / "docir-api.db"
    user_store = UserStore(database)
    assert user_store.create(
        UserRecord(
            id="u1",
            username="alice",
            password_hash="hash",
            status="active",
        )
    )
    GroupStore(database)
    chat_store = ChatStore(database)
    run_migrations(database)
    conversation_id = chat_store.create_conversation("u1")["conversation_id"]
    agent = _Agent()
    mm_sessions = _MMSessions(conversation_id)
    attachment_store = UserAttachmentStore(
        tmp_path / "backend" / "data" / "user",
        max_bytes=200 * 1024 * 1024,
    )
    state = SimpleNamespace(
        user_store=user_store,
        chat_store=chat_store,
        profile_builder=_ProfileBuilder(),
        conversation_turn_coordinator=ConversationTurnCoordinator(database),
        mm_sessions=mm_sessions,
        user_attachment_store=attachment_store,
        agent=agent,
        rag_service=object(),
        personal_knowledge_retrieval_service=object(),
    )
    return state, agent, chat_store, conversation_id


def test_upload_attachment_returns_docir_frontend_contract(tmp_path):
    """验证 `upload_attachment_returns_docir_frontend_contract` 场景。"""
    state, _agent, _chat_store, conversation_id = _state(tmp_path)
    app = FastAPI()
    for key, value in state.__dict__.items():
        setattr(app.state, key, value)
    app.include_router(chat.router)
    app.dependency_overrides[get_current_session] = lambda: SessionPrincipal(
        session_id="s1", user_id="u1"
    )

    response = _ASGIClient(app).post(
        f"/conversations/{conversation_id}/attachments",
        files={"file": ("notes.pdf", b"pdf-content", "application/pdf")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload == {
        "id": payload["id"],
        "filename": "notes.pdf",
        "mode": "pending",
        "token_count": 0,
        "element_count": 0,
        "page_count": 0,
        "validation_status": "pending",
        "quality_issue_count": 0,
        "media_type": "application/pdf",
        "size_bytes": len(b"pdf-content"),
    }
    stored = state.user_attachment_store.get(
        user_id="u1",
        conversation_id=conversation_id,
        attachment_id=payload["id"],
    )
    assert stored is not None
    assert stored.source_path.read_bytes() == b"pdf-content"
    assert state.mm_sessions.prepare_calls == 0


def test_attachment_prepare_and_status_endpoints(tmp_path):
    """验证显式 prepare 与状态查询复用现有附件授权边界。"""
    state, _agent, _chat_store, conversation_id = _state(tmp_path)
    app = FastAPI()
    for key, value in state.__dict__.items():
        setattr(app.state, key, value)
    app.include_router(chat.router)
    app.dependency_overrides[get_current_session] = lambda: SessionPrincipal(
        session_id="s1", user_id="u1"
    )
    uploaded = _ASGIClient(app).post(
        f"/conversations/{conversation_id}/attachments",
        files={"file": ("notes.pdf", b"pdf-content", "application/pdf")},
    ).json()
    attachment_id = uploaded["id"]

    client = _ASGIClient(app)
    prepared = client.post(
        f"/conversations/{conversation_id}/attachments/{attachment_id}/prepare"
    )
    assert prepared.status_code == 202
    assert prepared.json()["status"] == "ready"
    current = client.get(
        f"/conversations/{conversation_id}/attachments/{attachment_id}/status"
    )
    assert current.status_code == 200
    assert current.json()["document_id"] == "doc-1"


def test_selected_attachment_is_exposed_as_unparsed_tool_context(tmp_path):
    """验证 `selected_attachment_is_exposed_as_unparsed_tool_context` 场景。"""
    state, agent, chat_store, conversation_id = _state(tmp_path)
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    session = SessionPrincipal(session_id="s1", user_id="u1")
    stored = asyncio.run(
        state.user_attachment_store.save(
            user_id="u1",
            conversation_id=conversation_id,
            filename="notes.pdf",
            media_type="application/pdf",
            read=_reader(b"pdf-content"),
        )
    )

    asyncio.run(
        chat.send_message(
            conversation_id,
            SendMessageRequest(
                content="总结附件",
                attachment_ids=[stored.attachment_id],
            ),
            request,
            session,
        )
    )

    context = agent.run_spec.execution_context
    assert context.user_id == "u1"
    assert context.authorized_resources.attachment_ids == (stored.attachment_id,)
    prompt = agent.run_spec.messages[0]["content"]
    assert "尚未解析" in prompt
    assert stored.attachment_id in prompt
    assert "二叉树课程讲义" not in prompt
    assert state.mm_sessions.prepare_calls == 0
    stored = chat_store.get_model_messages(conversation_id)
    assert stored[0]["content"] == "总结附件"
    assert "二叉树课程讲义" not in stored[0]["content"]


def test_follow_up_reuses_latest_conversation_attachment_authorization(tmp_path):
    """A text-only follow-up can keep discussing the latest selected file."""
    state, agent, chat_store, conversation_id = _state(tmp_path)
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    session = SessionPrincipal(session_id="s1", user_id="u1")
    stored = asyncio.run(
        state.user_attachment_store.save(
            user_id="u1",
            conversation_id=conversation_id,
            filename="notes.pdf",
            media_type="application/pdf",
            read=_reader(b"pdf-content"),
        )
    )

    asyncio.run(
        chat.send_message(
            conversation_id,
            SendMessageRequest(
                content="先总结附件",
                attachment_ids=[stored.attachment_id],
            ),
            request,
            session,
        )
    )
    asyncio.run(
        chat.send_message(
            conversation_id,
            SendMessageRequest(content="展开刚才重建的部分"),
            request,
            session,
        )
    )

    context = agent.run_spec.execution_context
    assert context.authorized_resources.attachment_ids == (stored.attachment_id,)
    history = chat_store.get_history(conversation_id)
    follow_up = next(item for item in history if item["content"] == "展开刚才重建的部分")
    assert follow_up["attachments"] == []


def test_new_attachment_turn_does_not_expose_previous_attachment_ids(tmp_path):
    """连续上传文件时，模型只能看到当前轮的附件 ID。"""
    state, agent, _chat_store, conversation_id = _state(tmp_path)
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    session = SessionPrincipal(session_id="s1", user_id="u1")

    first = asyncio.run(
        state.user_attachment_store.save(
            user_id="u1",
            conversation_id=conversation_id,
            filename="first.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            read=_reader(b"first-docx"),
        )
    )
    second = asyncio.run(
        state.user_attachment_store.save(
            user_id="u1",
            conversation_id=conversation_id,
            filename="second.pdf",
            media_type="application/pdf",
            read=_reader(b"second-pdf"),
        )
    )

    for item in (first, second):
        asyncio.run(
            chat.send_message(
                conversation_id,
                SendMessageRequest(
                    content="看看这个附件",
                    attachment_ids=[item.attachment_id],
                ),
                request,
                session,
            )
        )

    prompt = "\n".join(str(message) for message in agent.run_spec.messages)
    assert second.attachment_id in prompt
    assert first.attachment_id not in prompt


def _reader(payload: bytes):
    """处理 `_reader` 相关逻辑。"""
    sent = False

    async def read(_size: int) -> bytes:
        """读取 `read` 相关数据。"""
        nonlocal sent
        if sent:
            return b""
        sent = True
        return payload

    return read


def test_missing_attachment_is_rejected_before_user_message_is_persisted(tmp_path):
    """验证 `missing_attachment_is_rejected_before_user_message_is_persisted` 场景。"""
    state, _agent, chat_store, conversation_id = _state(tmp_path)
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    session = SessionPrincipal(session_id="s1", user_id="u1")

    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            chat.send_message(
                conversation_id,
                SendMessageRequest(
                    content="总结附件",
                    attachment_ids=["missing"],
                ),
                request,
                session,
            )
        )

    assert raised.value.status_code == 404
    assert chat_store.get_model_messages(conversation_id) == []
