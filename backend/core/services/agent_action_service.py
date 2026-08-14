"""Approval and idempotent execution coordinator for high-impact actions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


class AgentActionService:
    def __init__(
        self,
        store: Any,
        *,
        validators: dict[str, Callable[[dict[str, Any]], None]] | None = None,
        executors: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] | None = None,
        policy_modes: dict[str, str] | None = None,
    ) -> None:
        self.store = store
        self.validators = validators or {}
        self.executors = executors or {}
        self.policy_modes = policy_modes or {}
        invalid = set(self.policy_modes.values()) - {
            "automatic",
            "approval_required",
            "forbidden",
        }
        if invalid:
            raise ValueError(f"invalid action policy modes: {sorted(invalid)}")

    @staticmethod
    def idempotency_key(
        user_id: str,
        action_type: str,
        arguments: dict[str, Any],
        explicit: str | None = None,
    ) -> str:
        if explicit:
            return explicit
        canonical = json.dumps(
            [user_id, action_type, arguments],
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def request(
        self,
        *,
        user_id: str,
        conversation_id: str,
        workspace_type: str,
        action_type: str,
        arguments: dict[str, Any],
        resource_snapshot: dict[str, Any],
        policy_id: str,
        approval_mode: str | None = None,
        idempotency_key: str | None = None,
        ttl_minutes: int = 30,
    ) -> dict[str, Any]:
        configured_mode = self.policy_modes.get(policy_id)
        mode = approval_mode or configured_mode or "approval_required"
        if mode == "forbidden":
            raise ValueError("action is forbidden by policy")
        if mode not in {"automatic", "approval_required"}:
            raise ValueError(f"invalid action approval mode: {mode!r}")
        if configured_mode is not None and configured_mode != mode:
            raise ValueError("action approval mode does not match policy")
        proposal = {
            "status": "proposed",
            "user_id": user_id,
            "conversation_id": conversation_id,
            "workspace_type": workspace_type,
            "action_type": action_type,
            "arguments": arguments,
            "resource_snapshot": resource_snapshot,
            "policy_id": policy_id,
        }
        validator = self.validators.get(action_type)
        if validator:
            validator(proposal)
        key = self.idempotency_key(user_id, action_type, arguments, idempotency_key)
        created = self.store.create(
            user_id=user_id,
            conversation_id=conversation_id,
            workspace_type=workspace_type,
            action_type=action_type,
            arguments=arguments,
            resource_snapshot=resource_snapshot,
            policy_id=policy_id,
            idempotency_key=key,
            expires_at=(
                datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
            ).isoformat(),
        )
        if mode == "automatic" and created["status"] == "pending":
            self.store.transition(
                created["action_id"],
                user_id,
                expected=("pending",),
                target="approved",
            )
            return self.execute(created["action_id"], user_id)
        return created

    def approve(self, action_id: str, user_id: str) -> dict[str, Any]:
        action = self.store.get(action_id, user_id)
        if action is None:
            raise KeyError(action_id)
        if self.policy_modes.get(action["policy_id"], "approval_required") != "approval_required":
            raise ValueError("action policy does not permit approval")
        if action["status"] != "pending":
            if action["status"] in {"approved", "executing", "succeeded", "failed"}:
                return action
            raise ValueError("action is not pending")
        if datetime.fromisoformat(action["expires_at"]) <= datetime.now(timezone.utc):
            try:
                self.store.transition(
                    action_id, user_id, expected=("pending",), target="expired"
                )
            except ValueError:
                current = self.store.get(action_id, user_id)
                if current is not None and current["status"] in {
                    "approved",
                    "executing",
                    "succeeded",
                    "failed",
                }:
                    return current
                raise
            raise ValueError("action expired")
        validator = self.validators.get(action["action_type"])
        if validator:
            validator(action)
        try:
            return self.store.transition(
                action_id, user_id, expected=("pending",), target="approved"
            )
        except ValueError:
            current = self.store.get(action_id, user_id)
            if current is not None and current["status"] in {
                "approved",
                "executing",
                "succeeded",
                "failed",
            }:
                return current
            raise

    def reject(self, action_id: str, user_id: str) -> dict[str, Any]:
        action = self.store.get(action_id, user_id)
        if action is None:
            raise KeyError(action_id)
        if action["status"] == "rejected":
            return action
        self._pending(action_id, user_id)
        return self.store.transition(
            action_id, user_id, expected=("pending",), target="rejected"
        )

    def execute(self, action_id: str, user_id: str) -> dict[str, Any]:
        action = self.store.get(action_id, user_id)
        if action is None:
            raise KeyError(action_id)
        if action["status"] in {"executing", "succeeded", "failed"}:
            return action
        if action["status"] != "approved":
            raise ValueError("action is not approved")
        validator = self.validators.get(action["action_type"])
        if validator:
            validator(action)
        try:
            executing = self.store.transition(
                action_id, user_id, expected=("approved",), target="executing"
            )
        except ValueError:
            current = self.store.get(action_id, user_id)
            if current is not None and current["status"] in {
                "executing",
                "succeeded",
                "failed",
            }:
                return current
            raise
        executor = self.executors.get(executing["action_type"])
        if executor is None:
            return self.store.transition(
                action_id,
                user_id,
                expected=("executing",),
                target="failed",
                error="executor unavailable",
            )
        try:
            result = executor(executing)
        except Exception as error:
            self.store.transition(
                action_id,
                user_id,
                expected=("executing",),
                target="failed",
                error=str(error),
            )
            raise
        return self.store.transition(
            action_id,
            user_id,
            expected=("executing",),
            target="succeeded",
            result=result,
        )

    def approve_and_execute(self, action_id: str, user_id: str) -> dict[str, Any]:
        self.approve(action_id, user_id)
        return self.execute(action_id, user_id)

    def _pending(self, action_id: str, user_id: str) -> dict[str, Any]:
        action = self.store.get(action_id, user_id)
        if action is None:
            raise KeyError(action_id)
        if action["status"] != "pending":
            raise ValueError("action is not pending")
        if datetime.fromisoformat(action["expires_at"]) <= datetime.now(timezone.utc):
            self.store.transition(
                action_id, user_id, expected=("pending",), target="expired"
            )
            raise ValueError("action expired")
        return action
