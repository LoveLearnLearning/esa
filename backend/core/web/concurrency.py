from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from contextlib import closing, suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType

from backend.core.stores.sqlite_connection import connect_sqlite

logger = logging.getLogger(__name__)


def _is_database_locked(error: sqlite3.OperationalError) -> bool:
    return "locked" in str(error).lower()


class ConversationTurnTimeoutError(TimeoutError):
    """等待同一对话的上一轮推理完成时超时。"""


class ConversationTurnTargetMissingError(LookupError):
    """获取租约时目标对话已被删除。"""


@dataclass
class _LockEntry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    references: int = 0


class KeyedLockLease:
    def __init__(self, pool: "KeyedAsyncLockPool", key: str, entry: _LockEntry):
        self._pool = pool
        self._key = key
        self._entry = entry
        self._released = False

    async def __aenter__(self) -> "KeyedLockLease":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.release()

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        await self._pool._release(self._key, self._entry)


class KeyedAsyncLockPool:
    """按业务键串行化当前进程内的协程，并自动回收空闲锁。"""

    def __init__(self) -> None:
        self._entries: dict[str, _LockEntry] = {}
        self._guard = asyncio.Lock()

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    async def acquire(self, key: str) -> KeyedLockLease:
        async with self._guard:
            entry = self._entries.setdefault(key, _LockEntry())
            entry.references += 1

        try:
            await entry.lock.acquire()
        except BaseException:
            await self._drop_reference(key, entry)
            raise

        return KeyedLockLease(self, key, entry)

    async def _release(self, key: str, entry: _LockEntry) -> None:
        entry.lock.release()
        await self._drop_reference(key, entry)

    async def _drop_reference(self, key: str, entry: _LockEntry) -> None:
        async with self._guard:
            entry.references -= 1
            if entry.references == 0 and self._entries.get(key) is entry:
                self._entries.pop(key, None)


class ConversationTurnLease:
    """同时持有进程内锁和 SQLite 跨进程租约。"""

    def __init__(
        self,
        coordinator: "ConversationTurnCoordinator",
        conversation_id: str,
        owner_token: str,
        local_lease: KeyedLockLease,
    ) -> None:
        self._coordinator = coordinator
        self._conversation_id = conversation_id
        self._owner_token = owner_token
        self._local_lease = local_lease
        self._released = False
        self._release_guard = asyncio.Lock()
        self._heartbeat_task = asyncio.create_task(self._heartbeat())

    async def __aenter__(self) -> "ConversationTurnLease":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.release()

    async def _heartbeat(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._coordinator.heartbeat_interval)
                try:
                    renewed = self._coordinator._renew_database_lease(
                        self._conversation_id,
                        self._owner_token,
                    )
                except sqlite3.Error:
                    logger.exception(
                        "刷新对话推理租约失败 conversation_id=%s",
                        self._conversation_id,
                    )
                    continue

                if not renewed:
                    logger.error(
                        "对话推理租约意外丢失 conversation_id=%s",
                        self._conversation_id,
                    )
                    return
        except asyncio.CancelledError:
            raise

    async def release(self) -> None:
        async with self._release_guard:
            if self._released:
                return
            self._released = True

            self._heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat_task

            try:
                for attempt in range(3):
                    try:
                        self._coordinator._release_database_lease(
                            self._conversation_id,
                            self._owner_token,
                        )
                        break
                    except sqlite3.OperationalError as error:
                        if not _is_database_locked(error):
                            raise
                        if attempt == 2:
                            logger.warning(
                                "释放对话推理租约时数据库持续繁忙，等待 TTL 回收 "
                                "conversation_id=%s",
                                self._conversation_id,
                            )
                            break
                        await asyncio.sleep(0.05 * (attempt + 1))
            except sqlite3.Error:
                # 租约最终会由 TTL 回收。释放失败不应覆盖已经生成的回复，
                # 但必须留下可定位的日志。
                logger.exception(
                    "释放对话推理租约失败，等待 TTL 回收 conversation_id=%s",
                    self._conversation_id,
                )
            finally:
                await self._local_lease.release()


class ConversationTurnCoordinator:
    """保证同一对话在多协程、多 Uvicorn worker 间一次只运行一轮。

    SQLite 行保存跨进程租约；本地 keyed lock 避免同一进程中的等待者频繁
    轮询数据库。租约会定期续期，进程崩溃后则在 TTL 到期时自动恢复。
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        lease_ttl: float = 300.0,
        heartbeat_interval: float = 30.0,
        wait_timeout: float = 600.0,
        poll_interval: float = 0.05,
    ) -> None:
        if lease_ttl <= 0:
            raise ValueError("lease_ttl 必须大于 0")
        if not 0 < heartbeat_interval < lease_ttl:
            raise ValueError("heartbeat_interval 必须大于 0 且小于 lease_ttl")
        if wait_timeout <= 0 or poll_interval <= 0:
            raise ValueError("wait_timeout 和 poll_interval 必须大于 0")

        self.database_path = Path(database_path)
        self.lease_ttl = lease_ttl
        self.heartbeat_interval = heartbeat_interval
        self.wait_timeout = wait_timeout
        self.poll_interval = poll_interval
        self._local_locks = KeyedAsyncLockPool()
        self._initialize_table()

    @property
    def local_entry_count(self) -> int:
        return self._local_locks.entry_count

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _initialize_table(self) -> None:
        with closing(connect_sqlite(self.database_path)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_turn_leases (
                    conversation_id TEXT PRIMARY KEY,
                    owner_token TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id)
                        REFERENCES conversations(conversation_id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_turn_leases_expires
                ON conversation_turn_leases (expires_at)
                """
            )

    def _try_acquire_database_lease(
        self,
        conversation_id: str,
        owner_token: str,
    ) -> bool:
        now = self._now()
        expires_at = now + timedelta(seconds=self.lease_ttl)
        with closing(
            connect_sqlite(self.database_path, timeout=0.25)
        ) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "DELETE FROM conversation_turn_leases WHERE expires_at <= ?",
                    (now.isoformat(),),
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO conversation_turn_leases (
                        conversation_id, owner_token, acquired_at, expires_at
                    )
                    SELECT ?, ?, ?, ?
                    WHERE EXISTS (
                        SELECT 1 FROM conversations WHERE conversation_id = ?
                    )
                    """,
                    (
                        conversation_id,
                        owner_token,
                        now.isoformat(),
                        expires_at.isoformat(),
                        conversation_id,
                    ),
                )
                inserted = bool(connection.execute("SELECT changes()").fetchone()[0])
                if not inserted:
                    exists = connection.execute(
                        "SELECT 1 FROM conversations WHERE conversation_id = ?",
                        (conversation_id,),
                    ).fetchone()
                    if exists is None:
                        raise ConversationTurnTargetMissingError(conversation_id)
                connection.commit()
                return inserted
            except BaseException:
                connection.rollback()
                raise

    def _renew_database_lease(
        self,
        conversation_id: str,
        owner_token: str,
    ) -> bool:
        expires_at = self._now() + timedelta(seconds=self.lease_ttl)
        with closing(
            connect_sqlite(self.database_path, timeout=0.25)
        ) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE conversation_turn_leases
                SET expires_at = ?
                WHERE conversation_id = ? AND owner_token = ?
                """,
                (expires_at.isoformat(), conversation_id, owner_token),
            )
            return cursor.rowcount == 1

    def _release_database_lease(
        self,
        conversation_id: str,
        owner_token: str,
    ) -> None:
        with closing(
            connect_sqlite(self.database_path, timeout=0.25)
        ) as connection, connection:
            connection.execute(
                """
                DELETE FROM conversation_turn_leases
                WHERE conversation_id = ? AND owner_token = ?
                """,
                (conversation_id, owner_token),
            )

    async def acquire(self, conversation_id: str) -> ConversationTurnLease:
        if not conversation_id:
            raise ValueError("conversation_id 不能为空")

        local_lease = await self._local_locks.acquire(conversation_id)
        owner_token = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.wait_timeout

        try:
            while True:
                try:
                    acquired = self._try_acquire_database_lease(
                        conversation_id,
                        owner_token,
                    )
                except sqlite3.OperationalError as error:
                    if not _is_database_locked(error):
                        raise
                    acquired = False
                if acquired:
                    return ConversationTurnLease(
                        self,
                        conversation_id,
                        owner_token,
                        local_lease,
                    )

                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise ConversationTurnTimeoutError(
                        f"等待对话 {conversation_id} 的上一轮生成完成超时"
                    )
                await asyncio.sleep(min(self.poll_interval, remaining))
        except BaseException:
            await local_lease.release()
            raise
