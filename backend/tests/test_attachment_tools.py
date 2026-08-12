import asyncio
from pathlib import Path
from types import SimpleNamespace

from backend.agent.tools.attachment_tools import (
    AttachmentToolContext,
    attachment_tool_context,
    parse_pdf_attachment,
)
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
            mode=SimpleNamespace(value="direct"),
            token_count=3,
            document=SimpleNamespace(
                elements=(object(),),
                source_page_count=1,
                parsed_page_count=1,
            ),
            context_for=lambda query: f"evidence for {query}",
        )


def test_attachment_tool_requires_current_message_authorization(tmp_path):
    store = UserAttachmentStore(tmp_path / "user", max_bytes=1024)
    item = asyncio.run(
        store.save(
            user_id="u1",
            conversation_id="c1",
            filename="notes.pdf",
            media_type="application/pdf",
            read=_reader(b"pdf"),
        )
    )
    sessions = _Sessions()
    denied = AttachmentToolContext(
        user_id="u1",
        conversation_id="c1",
        allowed_attachment_ids=frozenset(),
        store=store,
        mm_sessions=sessions,
    )
    with attachment_tool_context(denied):
        try:
            asyncio.run(parse_pdf_attachment(item.attachment_id, "总结"))
        except ValueError as error:
            assert "未在当前消息中授权" in str(error)
        else:
            raise AssertionError("unauthorized attachment was parsed")
    assert sessions.calls == 0


def test_attachment_tool_parses_lazily_after_authorization(tmp_path):
    store = UserAttachmentStore(tmp_path / "user", max_bytes=1024)
    item = asyncio.run(
        store.save(
            user_id="u1",
            conversation_id="c1",
            filename="notes.pdf",
            media_type="application/pdf",
            read=_reader(b"pdf"),
        )
    )
    sessions = _Sessions()
    context = AttachmentToolContext(
        user_id="u1",
        conversation_id="c1",
        allowed_attachment_ids=frozenset({item.attachment_id}),
        store=store,
        mm_sessions=sessions,
    )
    with attachment_tool_context(context):
        result = asyncio.run(parse_pdf_attachment(item.attachment_id, "总结"))

    assert result["mode"] == "direct"
    assert result["content"] == "evidence for 总结"
    assert sessions.calls == 1
