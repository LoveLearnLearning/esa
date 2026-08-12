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
        self.context = "<document filename=\"notes.pdf\">二叉树课程讲义</document>"

    async def prepare(self, session_id, paths):
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
        self.prompt_ctx = None

    async def run(self, content, username, **kwargs):
        self.prompt_ctx = kwargs["prompt_ctx"]
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
    state = SimpleNamespace(
        user_store=user_store,
        chat_store=chat_store,
        profile_builder=_ProfileBuilder(),
        conversation_turn_coordinator=ConversationTurnCoordinator(database),
        mm_sessions=_MMSessions(conversation_id),
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
    assert response.json() == {
        "id": "doc-1",
        "filename": "notes.pdf",
        "mode": "direct",
        "token_count": 32,
        "element_count": 2,
        "page_count": 2,
        "validation_status": "passed",
        "quality_issue_count": 0,
    }


def test_selected_attachment_is_injected_as_untrusted_docir_context(tmp_path):
    state, agent, chat_store, conversation_id = _state(tmp_path)
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    session = SessionPrincipal(session_id="s1", user_id="u1")

    asyncio.run(
        chat.send_message(
            conversation_id,
            SendMessageRequest(
                content="总结附件",
                attachment_ids=["doc-1"],
            ),
            request,
            session,
        )
    )

    assert "二叉树课程讲义" in agent.prompt_ctx.attachment_context
    stored = chat_store.get_model_messages(conversation_id)
    assert stored[0]["content"] == "总结附件"
    assert "二叉树课程讲义" not in stored[0]["content"]


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
