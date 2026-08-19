# backend/tests/test_conversation_title_service.py

"""Conversation title generation behavior and race protection."""

import asyncio

from backend.core.services.auxiliary_llm_service import AuxiliaryLLMUnavailable
from backend.core.services.conversation_title_service import ConversationTitleService
from backend.core.stores.chat_store import ChatStore
from backend.core.stores.group_store import GroupStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import UserRecord


class _TitleLLM:
    """Return a controllable title while recording auxiliary-model calls."""

    def __init__(self, result: str = "标题：**二叉树遍历方法**") -> None:
        """Initialize the fake title model."""

        self.result = result
        self.calls: list[tuple[list[dict], int, float]] = []

    async def chat(self, messages, *, max_tokens, temperature):
        """Record and return one fake completion."""

        self.calls.append((messages, max_tokens, temperature))
        return self.result


def _store(tmp_path) -> tuple[ChatStore, str]:
    """Create one user and one untitled conversation."""

    database_path = tmp_path / "titles.db"
    user_store = UserStore(database_path)
    assert user_store.create(
        UserRecord(
            id="u1",
            username="alice",
            password_hash="hash",
            status="active",
        )
    )
    GroupStore(database_path)
    chat_store = ChatStore(database_path)
    conversation_id = chat_store.create_conversation("u1")["conversation_id"]
    return chat_store, conversation_id


def test_first_question_generates_and_persists_clean_title(tmp_path):
    """The model title is cleaned and saved on the first question."""

    chat_store, conversation_id = _store(tmp_path)
    llm = _TitleLLM()
    service = ConversationTitleService(
        llm_client=llm,
        chat_store=chat_store,
    )

    title = asyncio.run(
        service.generate_for_first_question(
            conversation_id=conversation_id,
            user_id="u1",
            question="请给我讲一下二叉树的前序、中序和后序遍历",
        )
    )

    assert title == "二叉树遍历方法"
    assert chat_store.get_conversation(conversation_id)["title"] == title
    assert len(llm.calls) == 1
    assert llm.calls[0][1:] == (48, 0.2)


def test_generated_title_does_not_overwrite_manual_rename(tmp_path):
    """A manual rename wins if it races the model response."""

    chat_store, conversation_id = _store(tmp_path)

    class _RenamingLLM(_TitleLLM):
        """Rename the conversation while title generation is in flight."""

        async def chat(self, messages, *, max_tokens, temperature):
            """Simulate a user rename immediately before model completion."""

            chat_store.rename_conversation(conversation_id, "我的自定义标题")
            return await super().chat(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )

    service = ConversationTitleService(
        llm_client=_RenamingLLM(),
        chat_store=chat_store,
    )
    title = asyncio.run(
        service.generate_for_first_question(
            conversation_id=conversation_id,
            user_id="u1",
            question="解释快速排序",
        )
    )

    assert title is None
    assert chat_store.get_conversation(conversation_id)["title"] == "我的自定义标题"


def test_unavailable_small_model_uses_first_question_fallback(tmp_path):
    """A sidecar outage keeps chat usable and still produces a short title."""

    chat_store, conversation_id = _store(tmp_path)

    class _UnavailableLLM(_TitleLLM):
        """Simulate an unavailable auxiliary model."""

        async def chat(self, messages, *, max_tokens, temperature):
            """Raise the same error as the production auxiliary client."""

            raise AuxiliaryLLMUnavailable("offline")

    service = ConversationTitleService(
        llm_client=_UnavailableLLM(),
        chat_store=chat_store,
        max_title_chars=8,
    )
    title = asyncio.run(
        service.generate_for_first_question(
            conversation_id=conversation_id,
            user_id="u1",
            question="请详细解释操作系统中的虚拟内存",
        )
    )

    assert title == "请详细解释操作系"
    assert chat_store.get_conversation(conversation_id)["title"] == title
