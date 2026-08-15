# backend/core/stores/core_memory_store.py

"""Transactional persistence for CoreMemory V2; schema is migration-owned."""

from __future__ import annotations

import hashlib
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.agent.memories.core_memory_models import (
    CoreMemoryRecord,
    MemoryCandidate,
    MemoryRevisionConflict,
    MemoryScope,
)
from backend.core.stores.base_sqlite_store import BaseSQLiteStore


def _now() -> str:
    """处理 `_now` 相关逻辑。"""
    return datetime.now(timezone.utc).isoformat()


def _hash(content: str) -> str:
    """处理 `_hash` 相关逻辑。"""
    normalized = " ".join(content.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class CoreMemoryStore(BaseSQLiteStore):
    """封装 `core memory store` 数据持久化操作。"""
    def __init__(self, database_path: str | Path) -> None:
        """初始化 `CoreMemoryStore` 实例。"""
        self.database_path = Path(database_path)

    def _initialize(self) -> None:
        """初始化 `initialize` 相关数据。"""
        raise RuntimeError("CoreMemory schema must be installed by migrations")

    @staticmethod
    def _record(row) -> CoreMemoryRecord:
        """处理 `_record` 相关逻辑。"""
        return CoreMemoryRecord(
            memory_id=row["memory_id"],
            user_id=row["user_id"],
            memory_key=row["memory_key"],
            content=row["content"],
            category=row["category"],
            scope=MemoryScope(row["scope_type"], row["workspace_type"]),
            status=row["status"],
            source_type=row["source_type"],
            revision=int(row["revision"]),
            confirmed_at=row["confirmed_at"],
            review_after=row["review_after"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _candidate(row) -> MemoryCandidate:
        """处理 `_candidate` 相关逻辑。"""
        return MemoryCandidate(
            candidate_id=row["candidate_id"],
            user_id=row["user_id"],
            memory_id=row["memory_id"],
            memory_key=row["memory_key"],
            proposed_content=row["proposed_content"],
            category=row["category"],
            scope=MemoryScope(row["scope_type"], row["workspace_type"]),
            candidate_type=row["candidate_type"],
            status=row["status"],
            expected_revision=row["expected_revision"],
            resulting_memory_id=row["resulting_memory_id"],
            created_at=row["created_at"],
            decided_at=row["decided_at"],
            expires_at=row["expires_at"],
        )

    @staticmethod
    def _scope_clause(scope: MemoryScope) -> tuple[str, tuple[object, ...]]:
        """处理 `_scope_clause` 相关逻辑。"""
        if scope.scope_type == "global":
            return "scope_type='global' AND workspace_type IS NULL", ()
        return "scope_type='workspace' AND workspace_type=?", (scope.workspace_type,)

    def get(self, memory_id: str, user_id: str) -> CoreMemoryRecord | None:
        """获取 `get` 相关数据。

        Args:
            memory_id: str => memory ID。
            user_id: str => 用户 ID。

        Returns:
            CoreMemoryRecord | None => 处理结果。
        """
        row = self.query_one(
            "SELECT * FROM core_memories WHERE memory_id=? AND user_id=?",
            (memory_id, user_id),
        )
        return self._record(row) if row is not None else None

    def get_by_key(
        self, user_id: str, memory_key: str, scope: MemoryScope
    ) -> CoreMemoryRecord | None:
        """获取 `by key` 相关数据。

        Args:
            user_id: str => 用户 ID。
            memory_key: str => `memory_key` 参数。
            scope: MemoryScope => `scope` 参数。

        Returns:
            CoreMemoryRecord | None => 处理结果。
        """
        clause, params = self._scope_clause(scope)
        row = self.query_one(
            f"SELECT * FROM core_memories WHERE user_id=? AND memory_key=? AND {clause}",
            (user_id, memory_key, *params),
        )
        return self._record(row) if row is not None else None

    def list_visible(
        self,
        user_id: str,
        scopes: tuple[MemoryScope, ...],
        *,
        include_suppressed: bool = False,
    ) -> list[CoreMemoryRecord]:
        """列出 `visible` 相关数据。

        Args:
            user_id: str => 用户 ID。
            scopes: tuple[MemoryScope, ...] => `scopes` 参数。
            include_suppressed: bool => `include_suppressed` 参数。

        Returns:
            list[CoreMemoryRecord] => 处理结果。
        """
        clauses: list[str] = []
        params: list[object] = [user_id]
        for scope in scopes:
            clause, values = self._scope_clause(scope)
            clauses.append(f"({clause})")
            params.extend(values)
        if not clauses:
            return []
        status_clause = "" if include_suppressed else " AND status='active'"
        params.append(_now())
        rows = self.query_all(
            f"SELECT * FROM core_memories WHERE user_id=? AND ({' OR '.join(clauses)})"
            f"{status_clause} AND (expires_at IS NULL OR expires_at>?) "
            "ORDER BY updated_at DESC",
            tuple(params),
        )
        return [self._record(row) for row in rows]

    def list_user(
        self, user_id: str, *, limit: int = 100, offset: int = 0
    ) -> list[CoreMemoryRecord]:
        """列出 `user` 相关数据。

        Args:
            user_id: str => 用户 ID。
            limit: int => 返回数量上限。
            offset: int => 分页偏移量。

        Returns:
            list[CoreMemoryRecord] => 处理结果。
        """
        return [
            self._record(row)
            for row in self.query_all(
                "SELECT * FROM core_memories WHERE user_id=? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (user_id, max(1, min(limit, 200)), max(0, offset)),
            )
        ]

    @staticmethod
    def _advance_revision(connection, user_id: str, now: str) -> None:
        """处理 `_advance_revision` 相关逻辑。"""
        connection.execute(
            """INSERT INTO core_memory_user_revisions(user_id, revision, updated_at)
               VALUES (?, 1, ?)
               ON CONFLICT(user_id) DO UPDATE SET revision=revision+1, updated_at=excluded.updated_at""",
            (user_id, now),
        )

    @staticmethod
    def _audit(
        connection, record: CoreMemoryRecord, event: str, request_id: str
    ) -> None:
        """处理 `_audit` 相关逻辑。"""
        connection.execute(
            """INSERT INTO core_memory_audit_log
               (event_id,memory_id,user_id,event_type,scope_type,workspace_type,
                revision,content_hash,request_id,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                uuid4().hex,
                record.memory_id,
                record.user_id,
                event,
                record.scope.scope_type,
                record.scope.workspace_type,
                record.revision,
                _hash(record.content),
                request_id,
                _now(),
            ),
        )

    @staticmethod
    def _audit_candidate(
        connection,
        candidate: MemoryCandidate,
        event: str,
        request_id: str,
        *,
        resulting_memory_id: str | None = None,
        revision: int | None = None,
    ) -> None:
        """处理 `_audit_candidate` 相关逻辑。"""
        connection.execute(
            """INSERT INTO core_memory_audit_log
               (event_id,memory_id,user_id,event_type,scope_type,workspace_type,
                revision,content_hash,request_id,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                uuid4().hex,
                resulting_memory_id or candidate.memory_id,
                candidate.user_id,
                event,
                candidate.scope.scope_type,
                candidate.scope.workspace_type,
                revision,
                _hash(candidate.proposed_content or ""),
                request_id,
                _now(),
            ),
        )

    def audit_event(
        self,
        *,
        user_id: str,
        event: str,
        request_id: str,
        scope: MemoryScope | None = None,
        memory_id: str | None = None,
        revision: int | None = None,
    ) -> None:
        """处理 `audit_event` 相关逻辑。

        Args:
            user_id: str => 用户 ID。
            event: str => `event` 参数。
            request_id: str => request ID。
            scope: MemoryScope | None => `scope` 参数。
            memory_id: str | None => memory ID。
            revision: int | None => `revision` 参数。
        """
        self.execute(
            """INSERT INTO core_memory_audit_log
               (event_id,memory_id,user_id,event_type,scope_type,workspace_type,
                revision,request_id,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                uuid4().hex,
                memory_id,
                user_id,
                event,
                scope.scope_type if scope else None,
                scope.workspace_type if scope else None,
                revision,
                request_id,
                _now(),
            ),
        )

    def create(
        self,
        *,
        user_id: str,
        memory_key: str,
        content: str,
        category: str,
        scope: MemoryScope,
        source_type: str,
        source_conversation_id: str | None,
        request_id: str,
        review_after: str | None = None,
        expires_at: str | None = None,
        changed_via: str = "user_api",
        source_candidate_id: str | None = None,
    ) -> CoreMemoryRecord:
        """创建 `create` 相关数据。

        Args:
            user_id: str => 用户 ID。
            memory_key: str => `memory_key` 参数。
            content: str => 待处理内容。
            category: str => `category` 参数。
            scope: MemoryScope => `scope` 参数。
            source_type: str => `source_type` 参数。
            source_conversation_id: str | None => source conversation ID。
            request_id: str => request ID。
            review_after: str | None => `review_after` 参数。
            expires_at: str | None => `expires_at` 参数。
            changed_via: str => `changed_via` 参数。
            source_candidate_id: str | None => source candidate ID。

        Returns:
            CoreMemoryRecord => 处理结果。
        """
        memory_id, now = uuid4().hex, _now()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO core_memories
                   (memory_id,user_id,memory_key,content,normalized_content_hash,category,
                    scope_type,workspace_type,status,source_type,source_conversation_id,
                    revision,confirmed_at,review_after,expires_at,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?, 'active',?,?,1,?,?,?,?,?)""",
                (
                    memory_id,
                    user_id,
                    memory_key,
                    content,
                    _hash(content),
                    category,
                    scope.scope_type,
                    scope.workspace_type,
                    source_type,
                    source_conversation_id,
                    now,
                    review_after,
                    expires_at,
                    now,
                    now,
                ),
            )
            connection.execute(
                """INSERT INTO core_memory_versions
                   (version_id,memory_id,user_id,revision,content,category,scope_type,
                    workspace_type,change_type,changed_via,source_candidate_id,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    uuid4().hex,
                    memory_id,
                    user_id,
                    1,
                    content,
                    category,
                    scope.scope_type,
                    scope.workspace_type,
                    "create",
                    changed_via,
                    source_candidate_id,
                    now,
                ),
            )
            self._advance_revision(connection, user_id, now)
            row = connection.execute(
                "SELECT * FROM core_memories WHERE memory_id=? AND user_id=?",
                (memory_id, user_id),
            ).fetchone()
            assert row is not None
            record = self._record(row)
            self._audit(connection, record, "memory.created", request_id)
        return record

    def update(
        self,
        *,
        memory_id: str,
        user_id: str,
        expected_revision: int,
        content: str,
        category: str,
        request_id: str,
        change_type: str = "update",
        changed_via: str = "user_api",
        source_candidate_id: str | None = None,
    ) -> CoreMemoryRecord:
        """更新 `update` 相关数据。

        Args:
            memory_id: str => memory ID。
            user_id: str => 用户 ID。
            expected_revision: int => `expected_revision` 参数。
            content: str => 待处理内容。
            category: str => `category` 参数。
            request_id: str => request ID。
            change_type: str => `change_type` 参数。
            changed_via: str => `changed_via` 参数。
            source_candidate_id: str | None => source candidate ID。

        Returns:
            CoreMemoryRecord => 处理结果。
        """
        now = _now()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM core_memories WHERE memory_id=? AND user_id=?",
                (memory_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError(memory_id)
            current = int(row["revision"])
            if current != expected_revision:
                raise MemoryRevisionConflict(current)
            revision = current + 1
            connection.execute(
                """UPDATE core_memories SET content=?,normalized_content_hash=?,category=?,
                   revision=?,confirmed_at=?,updated_at=? WHERE memory_id=? AND user_id=?""",
                (
                    content,
                    _hash(content),
                    category,
                    revision,
                    now,
                    now,
                    memory_id,
                    user_id,
                ),
            )
            connection.execute(
                """INSERT INTO core_memory_versions
                   (version_id,memory_id,user_id,revision,content,category,scope_type,
                    workspace_type,change_type,changed_via,source_candidate_id,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    uuid4().hex,
                    memory_id,
                    user_id,
                    revision,
                    content,
                    category,
                    row["scope_type"],
                    row["workspace_type"],
                    change_type,
                    changed_via,
                    source_candidate_id,
                    now,
                ),
            )
            self._advance_revision(connection, user_id, now)
            updated = connection.execute(
                "SELECT * FROM core_memories WHERE memory_id=? AND user_id=?",
                (memory_id, user_id),
            ).fetchone()
            assert updated is not None
            record = self._record(updated)
            self._audit(connection, record, "memory.updated", request_id)
        return record

    def set_suppressed(
        self, memory_id: str, user_id: str, suppressed: bool, request_id: str
    ) -> CoreMemoryRecord:
        """设置 `suppressed` 相关数据。

        Args:
            memory_id: str => memory ID。
            user_id: str => 用户 ID。
            suppressed: bool => `suppressed` 参数。
            request_id: str => request ID。

        Returns:
            CoreMemoryRecord => 处理结果。
        """
        now, status = _now(), "suppressed" if suppressed else "active"
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE core_memories SET status=?,updated_at=? WHERE memory_id=? AND user_id=?",
                (status, now, memory_id, user_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(memory_id)
            self._advance_revision(connection, user_id, now)
            row = connection.execute(
                "SELECT * FROM core_memories WHERE memory_id=? AND user_id=?",
                (memory_id, user_id),
            ).fetchone()
            assert row is not None
            record = self._record(row)
            self._audit(
                connection,
                record,
                "memory.suppressed" if suppressed else "memory.restored",
                request_id,
            )
        return record

    def versions(self, memory_id: str, user_id: str) -> list[dict]:
        """处理 `versions` 相关逻辑。

        Args:
            memory_id: str => memory ID。
            user_id: str => 用户 ID。

        Returns:
            list[dict] => 处理结果。
        """
        return [
            dict(row)
            for row in self.query_all(
                "SELECT * FROM core_memory_versions WHERE memory_id=? AND user_id=? ORDER BY revision DESC",
                (memory_id, user_id),
            )
        ]

    def restore_version(
        self,
        memory_id: str,
        user_id: str,
        revision: int,
        expected_revision: int,
        request_id: str,
    ) -> CoreMemoryRecord:
        """处理 `restore_version` 相关逻辑。

        Args:
            memory_id: str => memory ID。
            user_id: str => 用户 ID。
            revision: int => `revision` 参数。
            expected_revision: int => `expected_revision` 参数。
            request_id: str => request ID。

        Returns:
            CoreMemoryRecord => 处理结果。
        """
        row = self.query_one(
            "SELECT content,category FROM core_memory_versions WHERE memory_id=? AND user_id=? AND revision=?",
            (memory_id, user_id, revision),
        )
        if row is None:
            raise KeyError(revision)
        return self.update(
            memory_id=memory_id,
            user_id=user_id,
            expected_revision=expected_revision,
            content=row["content"],
            category=row["category"],
            request_id=request_id,
            change_type="restore",
        )

    def forget(self, memory_id: str, user_id: str, request_id: str) -> bool:
        """处理 `forget` 相关逻辑。

        Args:
            memory_id: str => memory ID。
            user_id: str => 用户 ID。
            request_id: str => request ID。

        Returns:
            bool => 处理结果。
        """
        now = _now()
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT revision FROM core_memories WHERE memory_id=? AND user_id=?",
                (memory_id, user_id),
            ).fetchone()
            if row is None:
                return False
            final_revision = int(row["revision"])
            connection.execute(
                "DELETE FROM core_memory_candidates WHERE user_id=? AND (memory_id=? OR resulting_memory_id=?)",
                (user_id, memory_id, memory_id),
            )
            connection.execute(
                "DELETE FROM core_memories WHERE memory_id=? AND user_id=?",
                (memory_id, user_id),
            )
            connection.execute(
                "INSERT INTO core_memory_tombstones(memory_id,user_id,deleted_at,final_revision) VALUES (?,?,?,?)",
                (memory_id, user_id, now, final_revision),
            )
            connection.execute(
                """INSERT INTO core_memory_audit_log
                   (event_id,memory_id,user_id,event_type,revision,request_id,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    uuid4().hex,
                    memory_id,
                    user_id,
                    "memory.deleted",
                    final_revision,
                    request_id,
                    now,
                ),
            )
            self._advance_revision(connection, user_id, now)
        return True

    def create_candidate(
        self,
        *,
        user_id: str,
        memory_id: str | None,
        memory_key: str,
        proposed_content: str,
        category: str,
        scope: MemoryScope,
        candidate_type: str,
        expected_revision: int | None,
        source_conversation_id: str | None,
        expires_at: str,
        request_id: str = "",
    ) -> MemoryCandidate:
        """创建 `candidate` 相关数据。

        Args:
            user_id: str => 用户 ID。
            memory_id: str | None => memory ID。
            memory_key: str => `memory_key` 参数。
            proposed_content: str => `proposed_content` 参数。
            category: str => `category` 参数。
            scope: MemoryScope => `scope` 参数。
            candidate_type: str => `candidate_type` 参数。
            expected_revision: int | None => `expected_revision` 参数。
            source_conversation_id: str | None => source conversation ID。
            expires_at: str => `expires_at` 参数。
            request_id: str => request ID。

        Returns:
            MemoryCandidate => 处理结果。
        """
        candidate_id, now = uuid4().hex, _now()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO core_memory_candidates
                   (candidate_id,user_id,memory_id,memory_key,proposed_content,
                    normalized_content_hash,category,scope_type,workspace_type,candidate_type,
                    status,expected_revision,source_conversation_id,created_at,expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?,?,?,?)""",
                (
                    candidate_id,
                    user_id,
                    memory_id,
                    memory_key,
                    proposed_content,
                    _hash(proposed_content),
                    category,
                    scope.scope_type,
                    scope.workspace_type,
                    candidate_type,
                    expected_revision,
                    source_conversation_id,
                    now,
                    expires_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM core_memory_candidates WHERE candidate_id=? AND user_id=?",
                (candidate_id, user_id),
            ).fetchone()
            assert row is not None
            candidate = self._candidate(row)
            self._audit_candidate(
                connection,
                candidate,
                "memory.candidate_created",
                request_id,
            )
        return candidate

    def get_candidate(self, candidate_id: str, user_id: str) -> MemoryCandidate | None:
        """获取 `candidate` 相关数据。

        Args:
            candidate_id: str => candidate ID。
            user_id: str => 用户 ID。

        Returns:
            MemoryCandidate | None => 处理结果。
        """
        row = self.query_one(
            "SELECT * FROM core_memory_candidates WHERE candidate_id=? AND user_id=?",
            (candidate_id, user_id),
        )
        return self._candidate(row) if row is not None else None

    def list_candidates(
        self, user_id: str, status: str = "pending"
    ) -> list[MemoryCandidate]:
        """列出 `candidates` 相关数据。

        Args:
            user_id: str => 用户 ID。
            status: str => `status` 参数。

        Returns:
            list[MemoryCandidate] => 处理结果。
        """
        return [
            self._candidate(row)
            for row in self.query_all(
                "SELECT * FROM core_memory_candidates WHERE user_id=? AND status=? ORDER BY created_at DESC",
                (user_id, status),
            )
        ]

    def decide_candidate(
        self,
        candidate_id: str,
        user_id: str,
        status: str,
        resulting_memory_id: str | None = None,
        request_id: str = "",
    ) -> bool:
        """处理 `decide_candidate` 相关逻辑。

        Args:
            candidate_id: str => candidate ID。
            user_id: str => 用户 ID。
            status: str => `status` 参数。
            resulting_memory_id: str | None => resulting memory ID。
            request_id: str => request ID。

        Returns:
            bool => 处理结果。
        """
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM core_memory_candidates WHERE candidate_id=? AND user_id=?",
                (candidate_id, user_id),
            ).fetchone()
            if row is None or row["status"] != "pending":
                return False
            candidate = self._candidate(row)
            updated = connection.execute(
                """UPDATE core_memory_candidates SET status=?,resulting_memory_id=?,decided_at=?
                   WHERE candidate_id=? AND user_id=? AND status='pending'""",
                (status, resulting_memory_id, _now(), candidate_id, user_id),
            ).rowcount
            if updated != 1:
                return False
            self._audit_candidate(
                connection,
                candidate,
                f"memory.candidate_{status}",
                request_id,
                resulting_memory_id=resulting_memory_id,
            )
        return True

    def accept_candidate(
        self,
        *,
        candidate_id: str,
        user_id: str,
        content: str,
        category: str,
        scope: MemoryScope,
        source_conversation_id: str | None,
        request_id: str,
    ) -> CoreMemoryRecord:
        """处理 `accept_candidate` 相关逻辑。

        Args:
            candidate_id: str => candidate ID。
            user_id: str => 用户 ID。
            content: str => 待处理内容。
            category: str => `category` 参数。
            scope: MemoryScope => `scope` 参数。
            source_conversation_id: str | None => source conversation ID。
            request_id: str => request ID。

        Returns:
            CoreMemoryRecord => 处理结果。
        """
        now = _now()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            candidate_row = connection.execute(
                "SELECT * FROM core_memory_candidates WHERE candidate_id=? AND user_id=?",
                (candidate_id, user_id),
            ).fetchone()
            if candidate_row is None or candidate_row["status"] != "pending":
                raise KeyError(candidate_id)
            candidate = self._candidate(candidate_row)
            if candidate.memory_id is None:
                memory_id = uuid4().hex
                connection.execute(
                    """INSERT INTO core_memories
                       (memory_id,user_id,memory_key,content,normalized_content_hash,category,
                        scope_type,workspace_type,status,source_type,source_conversation_id,
                        revision,confirmed_at,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?, 'active','inferred_confirmed',?,1,?,?,?)""",
                    (
                        memory_id,
                        user_id,
                        candidate.memory_key,
                        content,
                        _hash(content),
                        category,
                        scope.scope_type,
                        scope.workspace_type,
                        source_conversation_id,
                        now,
                        now,
                        now,
                    ),
                )
                revision = 1
                change_type = "create"
            else:
                if scope != candidate.scope:
                    raise ValueError(
                        "existing memory scope cannot be changed by candidate"
                    )
                memory_id = candidate.memory_id
                memory_row = connection.execute(
                    "SELECT * FROM core_memories WHERE memory_id=? AND user_id=?",
                    (memory_id, user_id),
                ).fetchone()
                if memory_row is None:
                    raise KeyError(memory_id)
                current_revision = int(memory_row["revision"])
                if current_revision != (candidate.expected_revision or 0):
                    raise MemoryRevisionConflict(current_revision)
                revision = current_revision + 1
                change_type = "replace"
                connection.execute(
                    """UPDATE core_memories SET content=?,normalized_content_hash=?,category=?,
                       revision=?,confirmed_at=?,updated_at=? WHERE memory_id=? AND user_id=?""",
                    (
                        content,
                        _hash(content),
                        category,
                        revision,
                        now,
                        now,
                        memory_id,
                        user_id,
                    ),
                )
            connection.execute(
                """INSERT INTO core_memory_versions
                   (version_id,memory_id,user_id,revision,content,category,scope_type,
                    workspace_type,change_type,changed_via,source_candidate_id,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,'candidate',?,?)""",
                (
                    uuid4().hex,
                    memory_id,
                    user_id,
                    revision,
                    content,
                    category,
                    scope.scope_type,
                    scope.workspace_type,
                    change_type,
                    candidate_id,
                    now,
                ),
            )
            decided = connection.execute(
                """UPDATE core_memory_candidates SET status='accepted',resulting_memory_id=?,decided_at=?
                   WHERE candidate_id=? AND user_id=? AND status='pending'""",
                (memory_id, now, candidate_id, user_id),
            ).rowcount
            if decided != 1:
                raise MemoryRevisionConflict(revision)
            self._advance_revision(connection, user_id, now)
            record_row = connection.execute(
                "SELECT * FROM core_memories WHERE memory_id=? AND user_id=?",
                (memory_id, user_id),
            ).fetchone()
            assert record_row is not None
            record = self._record(record_row)
            self._audit(
                connection,
                record,
                "memory.created" if revision == 1 else "memory.updated",
                request_id,
            )
            self._audit_candidate(
                connection,
                candidate,
                "memory.candidate_accepted",
                request_id,
                resulting_memory_id=memory_id,
                revision=revision,
            )
            return record

    def user_revision(self, user_id: str) -> int:
        """处理 `user_revision` 相关逻辑。"""
        row = self.query_one(
            "SELECT revision FROM core_memory_user_revisions WHERE user_id=?",
            (user_id,),
        )
        return int(row["revision"]) if row is not None else 0
