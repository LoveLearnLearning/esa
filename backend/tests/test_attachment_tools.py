import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.agent.tools.common.attachment_tools import parse_pdf_attachment
from backend.agent.tools.context import AgentRuntimeDependencies, ToolExecutionContext
from backend.core.router.models import ResourceScope, WorkspaceRoute
from backend.core.services.user_attachment_service import UserAttachmentStore


def _reader(payload: bytes):
    sent = False

    async def read(_size: int) -> bytes:
        nonlocal sent
        if sent:
            return b""
        sent = True
        return payload

    return read


class _Sessions:
    def __init__(self) -> None:
        self.calls = 0

    async def prepare_attachment(self, session_id, attachment_id, path):
        self.calls += 1
        assert session_id == "c1"
        assert Path(path).read_bytes() == b"pdf"
        return SimpleNamespace(
            mode=SimpleNamespace(value="direct"), token_count=3,
            document=SimpleNamespace(
                elements=(object(),), source_page_count=1, parsed_page_count=1,
            ),
            context_for=lambda query: f"evidence for {query}",
        )


def _context(store, sessions, attachment_ids=()) -> ToolExecutionContext:
    scope = ResourceScope(
        attachment_ids=tuple(attachment_ids), metadata={"conversation_id": "c1"}
    )
    route = WorkspaceRoute(
        workspace_type="learning", agent_profile_id="learning.v1",
        skill_scopes=frozenset({"common", "learning"}),
        tool_scopes=frozenset({"common", "learning"}), prompt_key="learning.v1",
        profile_policy="learning.profile.v1", memory_policy_id="learning.memory.v1",
        resource_scope=scope, action_policy="learning.actions.v1",
    )
    return ToolExecutionContext(
        user_id="u1", conversation_id="c1", workspace_route=route,
        authorized_resources=scope, conversation_mode="normal",
        runtime_dependencies=AgentRuntimeDependencies(
            attachment_store=store,
            multimodal_sessions=sessions,
        ), request_id="r1", username="alice",
    )


def test_attachment_tool_requires_current_message_authorization(tmp_path):
    store = UserAttachmentStore(tmp_path / "user", max_bytes=1024)
    item = asyncio.run(store.save(
        user_id="u1", conversation_id="c1", filename="notes.pdf",
        media_type="application/pdf", read=_reader(b"pdf"),
    ))
    sessions = _Sessions()
    with pytest.raises(ValueError, match="未在当前消息中授权"):
        asyncio.run(parse_pdf_attachment(_context(store, sessions), item.attachment_id, "总结"))
    assert sessions.calls == 0


def test_attachment_tool_parses_lazily_after_authorization(tmp_path):
    store = UserAttachmentStore(tmp_path / "user", max_bytes=1024)
    item = asyncio.run(store.save(
        user_id="u1", conversation_id="c1", filename="notes.pdf",
        media_type="application/pdf", read=_reader(b"pdf"),
    ))
    sessions = _Sessions()
    result = asyncio.run(parse_pdf_attachment(
        _context(store, sessions, (item.attachment_id,)), item.attachment_id, "总结"
    ))
    assert result["mode"] == "direct"
    assert result["content"] == "evidence for 总结"
    assert sessions.calls == 1
