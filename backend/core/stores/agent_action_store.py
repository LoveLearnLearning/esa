"""Persistent Agent Action state machine; schema is migration-owned."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


class AgentActionStore(BaseSQLiteStore):
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def _initialize(self) -> None:
        raise RuntimeError("agent action schema must be installed by migrations")

    @staticmethod
    def _out(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["arguments"] = json.loads(item.pop("arguments_json"))
        item["resource_snapshot"] = json.loads(item.pop("resource_snapshot_json"))
        raw = item.pop("result_json")
        item["result"] = json.loads(raw) if raw else None
        return item

    def get(self, action_id: str, user_id: str) -> dict[str, Any] | None:
        row = self.query_one(
            "SELECT * FROM agent_action_requests WHERE action_id=? AND user_id=?",
            (action_id, user_id),
        )
        return self._out(row) if row is not None else None

    def get_by_idempotency(self, user_id: str, key: str) -> dict[str, Any] | None:
        row = self.query_one(
            "SELECT * FROM agent_action_requests WHERE user_id=? AND idempotency_key=?",
            (user_id, key),
        )
        return self._out(row) if row is not None else None

    def create(
        self,
        *,
        user_id: str,
        conversation_id: str,
        workspace_type: str,
        action_type: str,
        arguments: dict[str, Any],
        resource_snapshot: dict[str, Any],
        policy_id: str,
        idempotency_key: str,
        expires_at: str,
    ) -> dict[str, Any]:
        action_id, now = uuid4().hex, datetime.now(timezone.utc).isoformat()
        self.execute(
            """INSERT INTO agent_action_requests
               (action_id,user_id,conversation_id,workspace_type,action_type,
                arguments_json,resource_snapshot_json,policy_id,idempotency_key,
                status,created_at,expires_at)
               VALUES (?,?,?,?,?,?,?,?,?,'pending',?,?)
               ON CONFLICT(user_id,idempotency_key) DO NOTHING""",
            (
                action_id,
                user_id,
                conversation_id,
                workspace_type,
                action_type,
                json.dumps(arguments, ensure_ascii=False, sort_keys=True),
                json.dumps(resource_snapshot, ensure_ascii=False, sort_keys=True),
                policy_id,
                idempotency_key,
                now,
                expires_at,
            ),
        )
        item = self.get_by_idempotency(user_id, idempotency_key)
        if item is None:
            raise RuntimeError("agent action insert did not produce a record")
        return item

    def transition(
        self,
        action_id: str,
        user_id: str,
        *,
        expected: tuple[str, ...],
        target: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" for _ in expected)
        decided = now if target in {"approved", "rejected", "expired"} else None
        executed = now if target == "executing" else None
        completed = now if target in {"succeeded", "failed"} else None
        params = (
            target,
            json.dumps(result, ensure_ascii=False) if result is not None else None,
            error,
            decided,
            executed,
            completed,
            action_id,
            user_id,
            *expected,
        )
        count = self.execute(
            f"""UPDATE agent_action_requests SET status=?,
                result_json=COALESCE(?,result_json),error=COALESCE(?,error),
                decided_at=COALESCE(?,decided_at),executed_at=COALESCE(?,executed_at),
                completed_at=COALESCE(?,completed_at)
                WHERE action_id=? AND user_id=? AND status IN ({placeholders})""",
            params,
        )
        item = self.get(action_id, user_id)
        if item is None:
            raise KeyError(action_id)
        if count == 0:
            raise ValueError(f"invalid action transition {item['status']} -> {target}")
        return item

    def list(self, user_id: str, status: str | None = None) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM agent_action_requests WHERE user_id=?", [user_id]
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY created_at DESC"
        return [self._out(row) for row in self.query_all(sql, tuple(params))]
