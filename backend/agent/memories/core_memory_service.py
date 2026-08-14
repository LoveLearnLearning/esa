"""CoreMemory V2 application service and short-lived retrieval cache."""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from threading import RLock

from backend.agent.memories.core_memory_models import (
    CoreMemoryRecord,
    MemoryCandidate,
    MemoryScope,
)
from backend.agent.memories.core_memory_policy import CoreMemoryPolicy
from backend.agent.memories.core_memory_retrieval import CoreMemoryRetrieval
from backend.agent.tools.context import ToolExecutionContext
from backend.core.stores.core_memory_store import CoreMemoryStore

_KEY_RE = re.compile(r"[^a-z0-9_\u4e00-\u9fff]+")


def _key(value: str) -> str:
    normalized = _KEY_RE.sub("_", value.strip().casefold()).strip("_")
    if not normalized:
        raise ValueError("memory_key cannot be empty")
    return normalized[:64]


def _same(left: str, right: str) -> bool:
    return " ".join(left.casefold().split()) == " ".join(right.casefold().split())


class CoreMemoryService:
    def __init__(
        self,
        store: CoreMemoryStore,
        *,
        policy: CoreMemoryPolicy | None = None,
        retrieval: CoreMemoryRetrieval | None = None,
        projection=None,
        cache_ttl_seconds: float = 60.0,
    ) -> None:
        self.store = store
        self.policy = policy or CoreMemoryPolicy()
        self.retrieval = retrieval or CoreMemoryRetrieval()
        self.projection = projection
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[
            tuple[object, ...], tuple[float, list[dict[str, object]]]
        ] = {}
        self._cache_lock = RLock()

    @staticmethod
    def _source_conversation(context: ToolExecutionContext) -> str | None:
        return (
            None
            if context.conversation_id == "memory-management"
            else context.conversation_id
        )

    def search(
        self,
        context: ToolExecutionContext,
        query: str,
        *,
        category: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, object]]:
        scopes = self._visible_scopes(context, "memory.search")
        normalized_query = " ".join(query.casefold().split())
        revision = self.store.user_revision(context.user_id)
        cache_key = (
            context.user_id,
            context.workspace_route.workspace_type,
            tuple((scope.scope_type, scope.workspace_type) for scope in scopes),
            normalized_query,
            category,
            max(1, min(limit, 20)),
            revision,
            self.retrieval.version,
        )
        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached and cached[0] > now:
                return [dict(item) for item in cached[1]]
        records = self.store.list_visible(context.user_id, scopes)
        result = self.retrieval.rank(records, query, category=category, limit=limit)
        cache_seconds = self.cache_ttl_seconds
        expiring = [
            datetime.fromisoformat(item.expires_at)
            for item in records
            if item.expires_at
        ]
        if expiring:
            cache_seconds = min(
                cache_seconds,
                max(
                    0.0,
                    (min(expiring) - datetime.now(timezone.utc)).total_seconds(),
                ),
            )
        with self._cache_lock:
            self._cache[cache_key] = (now + cache_seconds, result)
        return [dict(item) for item in result]

    def list_visible(self, context: ToolExecutionContext) -> list[dict[str, object]]:
        scopes = self._visible_scopes(context, "memory.read")
        return [
            item.to_dict() for item in self.store.list_visible(context.user_id, scopes)
        ]

    def _visible_scopes(
        self,
        context: ToolExecutionContext,
        event: str,
    ) -> tuple[MemoryScope, ...]:
        try:
            scopes = self.policy.visible_scopes(context)
        except PermissionError:
            self.store.audit_event(
                user_id=context.user_id,
                event="memory.policy_denied",
                request_id=context.request_id,
            )
            raise
        self.store.audit_event(
            user_id=context.user_id,
            event=event,
            request_id=context.request_id,
            scope=scopes[-1] if scopes else None,
        )
        return scopes

    def _policy_value(self, context: ToolExecutionContext, operation):
        try:
            return operation()
        except PermissionError:
            self.store.audit_event(
                user_id=context.user_id,
                event="memory.policy_denied",
                request_id=context.request_id,
            )
            raise

    def _write_scope_content(
        self,
        context: ToolExecutionContext,
        scope_type: str,
        content: str,
    ) -> tuple[MemoryScope, str]:
        def resolve() -> tuple[MemoryScope, str]:
            self.policy.ensure_write(context)
            return (
                self.policy.resolve_scope(context, scope_type),
                self.policy.validate_content(context, content),
            )

        return self._policy_value(context, resolve)

    def _ensure_write(self, context: ToolExecutionContext) -> None:
        self._policy_value(context, lambda: self.policy.ensure_write(context))

    def _require_visible_record(
        self,
        context: ToolExecutionContext,
        memory_id: str,
    ) -> CoreMemoryRecord:
        current = self.store.get(memory_id, context.user_id)
        if current is None:
            raise KeyError(memory_id)
        visible = self._policy_value(
            context,
            lambda: self.policy.visible_scopes(context),
        )
        if current.scope not in visible:
            self.store.audit_event(
                user_id=context.user_id,
                event="memory.policy_denied",
                request_id=context.request_id,
                scope=current.scope,
                memory_id=current.memory_id,
                revision=current.revision,
            )
            raise PermissionError("memory is outside the current workspace scope")
        return current

    def list_all(
        self, user_id: str, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, object]]:
        return [
            item.to_dict()
            for item in self.store.list_user(user_id, limit=limit, offset=offset)
        ]

    def save_explicit(
        self,
        context: ToolExecutionContext,
        *,
        memory_key: str,
        content: str,
        category: str = "general",
        scope_type: str = "global",
    ) -> dict[str, object]:
        scope, content = self._write_scope_content(context, scope_type, content)
        memory_key = _key(memory_key)
        existing = self.store.get_by_key(context.user_id, memory_key, scope)
        if existing is None:
            record = self.store.create(
                user_id=context.user_id,
                memory_key=memory_key,
                content=content,
                category=category,
                scope=scope,
                source_type="explicit_user",
                source_conversation_id=self._source_conversation(context),
                request_id=context.request_id,
                changed_via="agent_tool",
            )
            self._project(record, context.request_id)
            return {"status": "created", "memory": record.to_dict()}
        if _same(existing.content, content) and existing.category == category:
            return {"status": "unchanged", "memory": existing.to_dict()}
        candidate = self.store.create_candidate(
            user_id=context.user_id,
            memory_id=existing.memory_id,
            memory_key=memory_key,
            proposed_content=content,
            category=category,
            scope=scope,
            candidate_type="replace",
            expected_revision=existing.revision,
            source_conversation_id=self._source_conversation(context),
            expires_at=(datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            request_id=context.request_id,
        )
        return {"status": "confirmation_required", "candidate": candidate.to_dict()}

    def propose_inferred(
        self,
        context: ToolExecutionContext,
        *,
        memory_key: str,
        content: str,
        category: str = "general",
        scope_type: str = "global",
    ) -> MemoryCandidate:
        scope, content = self._write_scope_content(context, scope_type, content)
        memory_key = _key(memory_key)
        existing = self.store.get_by_key(context.user_id, memory_key, scope)
        return self.store.create_candidate(
            user_id=context.user_id,
            memory_id=existing.memory_id if existing else None,
            memory_key=memory_key,
            proposed_content=content,
            category=category,
            scope=scope,
            candidate_type="replace" if existing else "create",
            expected_revision=existing.revision if existing else None,
            source_conversation_id=self._source_conversation(context),
            expires_at=(datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            request_id=context.request_id,
        )

    def create_for_user(
        self, context: ToolExecutionContext, **values
    ) -> CoreMemoryRecord:
        result = self.save_explicit(context, **values)
        memory = result.get("memory")
        if not isinstance(memory, dict):
            raise ValueError("memory conflicts with an existing value")
        record = self.store.get(str(memory["memory_id"]), context.user_id)
        assert record is not None
        return record

    def update(
        self,
        context: ToolExecutionContext,
        memory_id: str,
        *,
        expected_revision: int,
        content: str | None = None,
        category: str | None = None,
    ) -> CoreMemoryRecord:
        self._ensure_write(context)
        current = self._require_visible_record(context, memory_id)
        next_content = self._policy_value(
            context,
            lambda: self.policy.validate_content(context, content or current.content),
        )
        record = self.store.update(
            memory_id=memory_id,
            user_id=context.user_id,
            expected_revision=expected_revision,
            content=next_content,
            category=category or current.category,
            request_id=context.request_id,
        )
        self._project(record, context.request_id)
        return record

    def suppress(
        self, context: ToolExecutionContext, memory_id: str, suppressed: bool
    ) -> CoreMemoryRecord:
        self._ensure_write(context)
        self._require_visible_record(context, memory_id)
        record = self.store.set_suppressed(
            memory_id, context.user_id, suppressed, context.request_id
        )
        if self.projection is not None:
            try:
                if suppressed:
                    result = self.projection.remove_core_memory_projection(record)
                    if result.reason == "projection_removed":
                        self.store.audit_event(
                            user_id=record.user_id,
                            event="memory.projection_removed",
                            request_id=context.request_id,
                            scope=record.scope,
                            memory_id=record.memory_id,
                            revision=record.revision,
                        )
                else:
                    self._project(record, context.request_id)
            except Exception:
                pass
        return record

    def forget(self, context: ToolExecutionContext, memory_id: str) -> bool:
        self._ensure_write(context)
        current = self._require_visible_record(context, memory_id)
        forgotten = self.store.forget(memory_id, context.user_id, context.request_id)
        if forgotten and current is not None and self.projection is not None:
            try:
                result = self.projection.remove_core_memory_projection(current)
                if result.reason == "projection_removed":
                    self.store.audit_event(
                        user_id=current.user_id,
                        event="memory.projection_removed",
                        request_id=context.request_id,
                        scope=current.scope,
                        memory_id=current.memory_id,
                        revision=current.revision,
                    )
            except Exception:
                pass
        return forgotten

    def versions(self, user_id: str, memory_id: str) -> list[dict]:
        if self.store.get(memory_id, user_id) is None:
            raise KeyError(memory_id)
        return self.store.versions(memory_id, user_id)

    def restore_version(
        self,
        context: ToolExecutionContext,
        memory_id: str,
        revision: int,
        expected_revision: int,
    ) -> CoreMemoryRecord:
        self._ensure_write(context)
        self._require_visible_record(context, memory_id)
        record = self.store.restore_version(
            memory_id, context.user_id, revision, expected_revision, context.request_id
        )
        self._project(record, context.request_id)
        return record

    def list_candidates(self, user_id: str) -> list[dict[str, object]]:
        return [item.to_dict() for item in self.store.list_candidates(user_id)]

    def accept_candidate(
        self,
        context: ToolExecutionContext,
        candidate_id: str,
        *,
        content: str | None = None,
        category: str | None = None,
        scope_type: str | None = None,
    ) -> CoreMemoryRecord:
        self._ensure_write(context)
        candidate = self.store.get_candidate(candidate_id, context.user_id)
        if candidate is None or candidate.status != "pending":
            raise KeyError(candidate_id)
        if datetime.fromisoformat(candidate.expires_at) <= datetime.now(timezone.utc):
            self.store.decide_candidate(
                candidate_id,
                context.user_id,
                "expired",
                request_id=context.request_id,
            )
            raise ValueError("candidate expired")
        next_content = self._policy_value(
            context,
            lambda: self.policy.validate_content(
                context, content or candidate.proposed_content or ""
            ),
        )
        next_category = category or candidate.category
        next_scope = (
            self._policy_value(
                context,
                lambda: self.policy.resolve_scope(context, scope_type),
            )
            if scope_type
            else candidate.scope
        )
        record = self.store.accept_candidate(
            candidate_id=candidate_id,
            user_id=context.user_id,
            content=next_content,
            category=next_category,
            scope=next_scope,
            source_conversation_id=self._source_conversation(context),
            request_id=context.request_id,
        )
        self._project(record, context.request_id)
        return record

    def reject_candidate(
        self,
        user_id: str,
        candidate_id: str,
        *,
        request_id: str = "",
    ) -> bool:
        return self.store.decide_candidate(
            candidate_id,
            user_id,
            "rejected",
            request_id=request_id,
        )

    def _project(self, record: CoreMemoryRecord, request_id: str) -> None:
        if self.projection is None:
            return
        try:
            result = self.projection.project_core_memory(record)
            if result.projected:
                self.store.audit_event(
                    user_id=record.user_id,
                    event="memory.projection_created",
                    request_id=request_id,
                    scope=record.scope,
                    memory_id=record.memory_id,
                    revision=record.revision,
                )
        except Exception:
            pass
