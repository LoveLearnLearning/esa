# backend/tests/test_conversation_compression_service.py

"""验证 `conversation_compression_service` 相关行为与回归场景。"""

import asyncio
from datetime import datetime, timedelta, timezone

from backend.core.services.conversation_compression_service import (
    ConversationCompressionService,
)
from backend.core.stores.chat_store import ChatStore
from backend.core.stores.conversation_summary_store import ConversationSummaryStore
from backend.core.stores.migrations import run_migrations
from backend.core.stores.user_presence_store import UserPresenceStore
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import UserRecord


class _AuxiliaryLLM:
    """封装 `_AuxiliaryLLM` 的状态与行为。"""
    def __init__(self) -> None:
        """初始化 `_AuxiliaryLLM` 实例。"""
        self.calls = []

    async def chat(self, messages, *, max_tokens, temperature):
        """处理 `chat` 相关逻辑。

        Args:
            messages: object => 消息列表。
            max_tokens: object => `max_tokens` 参数。
            temperature: object => `temperature` 参数。

        Returns:
            object => 处理结果。
        """
        self.calls.append((messages, max_tokens, temperature))
        return "用户正在讨论离散数学；助手已解释前六条消息，后续问题尚待处理。"


def test_offline_compression_keeps_originals_and_recent_context(tmp_path):
    """验证 `offline_compression_keeps_originals_and_recent_context` 场景。"""
    database_path = tmp_path / "compression.db"
    user_store = UserStore(database_path)
    assert user_store.create(
        UserRecord(
            id="u1",
            username="alice",
            password_hash="hash",
            status="active",
        )
    )
    chat_store = ChatStore(database_path)
    run_migrations(database_path)
    conversation = chat_store.create_conversation("u1")
    conversation_id = conversation["conversation_id"]
    chat_store.append_messages(
        conversation_id,
        [
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"message-{index}",
            }
            for index in range(14)
        ],
    )
    presence_store = UserPresenceStore(database_path)
    presence_store.mark_offline("u1")
    summary_store = ConversationSummaryStore(database_path)
    summary_store.execute(
        """
        INSERT INTO conversation_turn_leases (
            conversation_id, owner_token, acquired_at, expires_at
        ) VALUES (?, 'expired', '2000-01-01T00:00:00+00:00',
                  '2000-01-01T00:01:00+00:00')
        """,
        (conversation_id,),
    )
    llm = _AuxiliaryLLM()
    service = ConversationCompressionService(
        llm_client=llm,
        summary_store=summary_store,
        offline_after_seconds=300,
        scan_interval_seconds=30,
        min_messages=12,
        min_new_messages=6,
        keep_recent_messages=8,
        max_input_chars=60000,
        max_output_tokens=2048,
    )

    assert asyncio.run(service.run_once()) == 1

    persisted = summary_store.get(conversation_id)
    assert persisted is not None
    assert persisted["source_message_count"] == 6
    assert persisted["summary"].startswith("用户正在讨论")
    assert len(chat_store.get_history(conversation_id)) == 14

    summary, recent = chat_store.get_compressed_model_history_and_append(
        conversation_id,
        [{"role": "user", "content": "current"}],
    )
    assert summary == persisted["summary"]
    assert [item["content"] for item in recent] == [
        f"message-{index}" for index in range(6, 14)
    ]
    assert len(chat_store.get_history(conversation_id)) == 15
    assert len(llm.calls) == 1


def test_summary_is_not_committed_after_user_returns_online(tmp_path):
    """验证 `summary_is_not_committed_after_user_returns_online` 场景。"""
    database_path = tmp_path / "online-race.db"
    user_store = UserStore(database_path)
    assert user_store.create(
        UserRecord(
            id="u1",
            username="alice",
            password_hash="hash",
            status="active",
        )
    )
    chat_store = ChatStore(database_path)
    run_migrations(database_path)
    conversation = chat_store.create_conversation("u1")
    conversation_id = conversation["conversation_id"]
    chat_store.append_messages(
        conversation_id,
        [{"role": "user", "content": f"message-{i}"} for i in range(12)],
    )
    presence_store = UserPresenceStore(database_path)
    presence_store.mark_offline("u1")
    summary_store = ConversationSummaryStore(database_path)

    class _ReturnOnlineLLM(_AuxiliaryLLM):
        """封装 `_ReturnOnlineLLM` 的状态与行为。"""
        async def chat(self, messages, *, max_tokens, temperature):
            """处理 `chat` 相关逻辑。

            Args:
                messages: object => 消息列表。
                max_tokens: object => `max_tokens` 参数。
                temperature: object => `temperature` 参数。

            Returns:
                object => 处理结果。
            """
            presence_store.mark_online("u1")
            return await super().chat(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )

    service = ConversationCompressionService(
        llm_client=_ReturnOnlineLLM(),
        summary_store=summary_store,
        offline_after_seconds=300,
        scan_interval_seconds=30,
        min_messages=12,
        min_new_messages=6,
        keep_recent_messages=8,
        max_input_chars=60000,
        max_output_tokens=2048,
    )

    assert asyncio.run(service.run_once()) == 0
    assert summary_store.get(conversation_id) is None


def test_active_compression_requires_live_owner_and_excludes_current_turn(tmp_path):
    database_path = tmp_path / "active-compression.db"
    user_store = UserStore(database_path)
    assert user_store.create(
        UserRecord(id="u1", username="alice", password_hash="hash", status="active")
    )
    chat_store = ChatStore(database_path)
    run_migrations(database_path)
    conversation_id = chat_store.create_conversation("u1")["conversation_id"]
    chat_store.append_messages(
        conversation_id,
        [{"role": "user", "content": f"prior-{index}"} for index in range(12)],
    )
    chat_store.append_messages(
        conversation_id,
        [{"role": "user", "content": "CURRENT-MUST-NOT-BE-SUMMARIZED"}],
    )
    current_id = chat_store.latest_message_id(conversation_id)
    assert current_id is not None

    summary_store = ConversationSummaryStore(database_path)
    now = datetime.now(timezone.utc)
    summary_store.execute(
        """
        INSERT INTO conversation_turn_leases (
            conversation_id, owner_token, acquired_at, expires_at
        ) VALUES (?, ?, ?, ?)
        """,
        (
            conversation_id,
            "owner",
            now.isoformat(),
            (now + timedelta(minutes=5)).isoformat(),
        ),
    )
    llm = _AuxiliaryLLM()
    service = ConversationCompressionService(
        llm_client=llm,
        summary_store=summary_store,
        offline_after_seconds=300,
        scan_interval_seconds=30,
        min_messages=4,
        min_new_messages=2,
        keep_recent_messages=2,
        max_input_chars=60000,
        max_output_tokens=768,
    )

    assert asyncio.run(service.compress_active_turn(
        conversation_id=conversation_id,
        owner_token="wrong-owner",
        before_message_id=current_id,
    )) is False
    assert summary_store.get(conversation_id) is None

    assert asyncio.run(service.compress_active_turn(
        conversation_id=conversation_id,
        owner_token="owner",
        before_message_id=current_id,
    )) is True
    stored = summary_store.get(conversation_id)
    assert stored is not None
    assert stored["summarized_through_message_id"] < current_id
    serialized_calls = str(llm.calls)
    assert "CURRENT-MUST-NOT-BE-SUMMARIZED" not in serialized_calls

    summary, history = chat_store.get_compressed_model_history_before(
        conversation_id,
        current_id,
    )
    assert summary == stored["summary"]
    assert all(item["content"] != "CURRENT-MUST-NOT-BE-SUMMARIZED" for item in history)


def test_owner_bound_summary_rejects_foreign_boundary(tmp_path):
    database_path = tmp_path / "foreign-boundary.db"
    user_store = UserStore(database_path)
    for user_id in ("u1", "u2"):
        assert user_store.create(
            UserRecord(
                id=user_id,
                username=user_id,
                password_hash="hash",
                status="active",
            )
        )
    chat_store = ChatStore(database_path)
    run_migrations(database_path)
    first = chat_store.create_conversation("u1")["conversation_id"]
    second = chat_store.create_conversation("u2")["conversation_id"]
    chat_store.append_messages(first, [{"role": "user", "content": "first"}])
    chat_store.append_messages(second, [{"role": "user", "content": "second"}])
    foreign_id = chat_store.latest_message_id(second)
    assert foreign_id is not None
    store = ConversationSummaryStore(database_path)
    now = datetime.now(timezone.utc)
    store.execute(
        """
        INSERT INTO conversation_turn_leases (
            conversation_id, owner_token, acquired_at, expires_at
        ) VALUES (?, 'owner', ?, ?)
        """,
        (first, now.isoformat(), (now + timedelta(minutes=5)).isoformat()),
    )

    assert store.upsert_if_turn_owned(
        conversation_id=first,
        owner_token="owner",
        summarized_through_message_id=foreign_id,
        summary="bad",
        source_message_count=1,
    ) is False
    assert store.get(first) is None
