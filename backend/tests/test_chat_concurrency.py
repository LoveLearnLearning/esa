import asyncio
import sqlite3
from types import SimpleNamespace

from backend.core.stores.chat_store import ChatStore
from backend.core.stores.group_store import GroupStore
from backend.core.stores.migrations import run_migrations
from backend.core.stores.user_store import UserStore
from backend.core.utils.models import SessionPrincipal, UserRecord
from backend.core.web.concurrency import ConversationTurnCoordinator
from backend.core.web.routers.chat import send_message
from backend.core.web.schemas import SendMessageRequest


class _ProfileBuilder:
    def build(self, query):
        return None


class _Agent:
    def __init__(self):
        self.active_runs = 0
        self.max_active_runs = 0

    async def run(self, content, username, **kwargs):
        self.active_runs += 1
        self.max_active_runs = max(self.max_active_runs, self.active_runs)
        try:
            await asyncio.sleep(0.02)
            return [
                {"role": "user", "content": content, "is_visible": True},
                {
                    "role": "assistant",
                    "content": f"reply:{content}",
                    "is_visible": True,
                },
            ]
        finally:
            self.active_runs -= 1


def _setup(database_path):
    user_store = UserStore(database_path)
    user_store.create(
        UserRecord(
            id="u1",
            username="alice",
            password_hash="hash",
            status="active",
        )
    )
    GroupStore(database_path)
    chat_store = ChatStore(database_path)
    run_migrations(database_path)
    conversation_id = chat_store.create_conversation("u1")["conversation_id"]
    return user_store, chat_store, conversation_id


def _request(user_store, chat_store, agent, coordinator):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                chat_store=chat_store,
                user_store=user_store,
                profile_builder=_ProfileBuilder(),
                agent=agent,
                conversation_turn_coordinator=coordinator,
            )
        )
    )


def test_same_conversation_turns_are_serialized(tmp_path):
    database_path = tmp_path / "chat.db"
    user_store, chat_store, conversation_id = _setup(database_path)
    agent = _Agent()
    coordinator = ConversationTurnCoordinator(database_path)
    request = _request(user_store, chat_store, agent, coordinator)
    session = SessionPrincipal(session_id="s1", user_id="u1")

    async def run_concurrently():
        await asyncio.gather(
            send_message(
                conversation_id,
                SendMessageRequest(content="first"),
                request,
                session,
            ),
            send_message(
                conversation_id,
                SendMessageRequest(content="second"),
                request,
                session,
            ),
        )

    asyncio.run(run_concurrently())

    assert agent.max_active_runs == 1
    assert [item["role"] for item in chat_store.get_model_messages(conversation_id)] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert coordinator.local_entry_count == 0
    assert chat_store.query_one("SELECT COUNT(*) FROM conversation_turn_leases")[0] == 0


def test_two_worker_coordinators_share_the_database_lease(tmp_path):
    """两个独立协调器没有共享内存锁，用数据库租约仍必须串行。"""
    database_path = tmp_path / "chat.db"
    user_store, chat_store, conversation_id = _setup(database_path)
    agent = _Agent()
    first_worker = ConversationTurnCoordinator(database_path)
    second_worker = ConversationTurnCoordinator(database_path)
    first_request = _request(user_store, chat_store, agent, first_worker)
    second_request = _request(user_store, chat_store, agent, second_worker)
    session = SessionPrincipal(session_id="s1", user_id="u1")

    async def run_across_workers():
        await asyncio.gather(
            send_message(
                conversation_id,
                SendMessageRequest(content="first"),
                first_request,
                session,
            ),
            send_message(
                conversation_id,
                SendMessageRequest(content="second"),
                second_request,
                session,
            ),
        )

    asyncio.run(run_across_workers())

    messages = chat_store.get_model_messages(conversation_id)
    assert agent.max_active_runs == 1
    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert messages[1]["content"] == f"reply:{messages[0]['content']}"
    assert messages[3]["content"] == f"reply:{messages[2]['content']}"


def test_expired_database_lease_is_recovered(tmp_path):
    database_path = tmp_path / "chat.db"
    _, chat_store, conversation_id = _setup(database_path)
    coordinator = ConversationTurnCoordinator(
        database_path,
        lease_ttl=1.0,
        heartbeat_interval=0.2,
        wait_timeout=1.0,
    )
    chat_store.execute(
        """
        INSERT INTO conversation_turn_leases (
            conversation_id, owner_token, acquired_at, expires_at
        ) VALUES (?, 'dead-worker', '2000-01-01T00:00:00+00:00',
                  '2000-01-01T00:00:01+00:00')
        """,
        (conversation_id,),
    )

    async def acquire_and_release():
        lease = await coordinator.acquire(conversation_id)
        await lease.release()

    asyncio.run(acquire_and_release())

    assert chat_store.query_one("SELECT COUNT(*) FROM conversation_turn_leases")[0] == 0


def test_transient_sqlite_write_lock_is_retried(tmp_path, monkeypatch):
    database_path = tmp_path / "chat.db"
    _, chat_store, conversation_id = _setup(database_path)
    coordinator = ConversationTurnCoordinator(
        database_path,
        wait_timeout=1.0,
        poll_interval=0.01,
    )
    original_try_acquire = coordinator._try_acquire_database_lease
    attempts = 0

    def briefly_locked(target_conversation_id, owner_token):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("database is locked")
        return original_try_acquire(target_conversation_id, owner_token)

    monkeypatch.setattr(
        coordinator,
        "_try_acquire_database_lease",
        briefly_locked,
    )

    async def acquire_and_release():
        lease = await coordinator.acquire(conversation_id)
        await lease.release()

    asyncio.run(acquire_and_release())

    assert attempts == 2
    assert chat_store.query_one("SELECT COUNT(*) FROM conversation_turn_leases")[0] == 0
