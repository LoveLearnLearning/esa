import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

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


class _ProfileBuilder:
    def build(self, query):
        return None


class _MMSessions:
    def __init__(self, conversation_id):
        self.conversation_id = conversation_id
        self.prepare_calls = 0

    async def prepare(self, session_id, paths):
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
        if session_id != self.conversation_id or attachment_id != "doc-1":
            raise KeyError(attachment_id)
        return self.context

    async def remove(self, session_id, attachment_id):
        return attachment_id == "doc-1"

    async def clear(self, session_id):
        return None


class _Agent:
    def __init__(self):
        self.run_spec = None

    async def run(self, run_spec):
        self.run_spec = run_spec
        content = run_spec.messages[-1]["content"]
        return [
            {"role": "user", "content": content, "is_visible": True},
            {"role": "assistant", "content": "done", "is_visible": True},
        ]


def _state(tmp_path):
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
    )
    return state, agent, chat_store, conversation_id


def test_upload_attachment_returns_docir_frontend_contract(tmp_path):
    state, _agent, _chat_store, conversation_id = _state(tmp_path)
    app = FastAPI()
    for key, value in state.__dict__.items():
        setattr(app.state, key, value)
    app.include_router(chat.router)
    app.dependency_overrides[get_current_session] = lambda: SessionPrincipal(
        session_id="s1", user_id="u1"
    )

    response = TestClient(app).post(
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


def test_selected_attachment_is_exposed_as_unparsed_tool_context(tmp_path):
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


def _reader(payload: bytes):
    sent = False

    async def read(_size: int) -> bytes:
        nonlocal sent
        if sent:
            return b""
        sent = True
        return payload

    return read


def test_missing_attachment_is_rejected_before_user_message_is_persisted(tmp_path):
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
