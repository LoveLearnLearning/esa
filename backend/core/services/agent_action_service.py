# backend/core/services/agent_action_service.py

"""Approval and idempotent execution coordinator for high-impact actions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


class AgentActionService:
    """提供 `agent action service` 领域服务。"""
    def __init__(
        self,
        store: Any,
        *,
        validators: dict[str, Callable[[dict[str, Any]], None]] | None = None,
        executors: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] | None = None,
    ) -> None:
        """初始化 `AgentActionService` 实例。"""
        self.store = store
        self.validators = validators or {}
        self.executors = executors or {}

    @staticmethod
    def idempotency_key(
        user_id: str,
        action_type: str,
        arguments: dict[str, Any],
        explicit: str | None = None,
    ) -> str:
        """处理 `idempotency_key` 相关逻辑。

        Args:
            user_id: str => 用户 ID。
            action_type: str => `action_type` 参数。
            arguments: dict[str, Any] => `arguments` 参数。
            explicit: str | None => `explicit` 参数。

        Returns:
            str => 处理结果。
        """
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
        idempotency_key: str | None = None,
        ttl_minutes: int = 30,
    ) -> dict[str, Any]:
        """处理 `request` 相关逻辑。

        Args:
            user_id: str => 用户 ID。
            conversation_id: str => 对话 ID。
            workspace_type: str => `workspace_type` 参数。
            action_type: str => `action_type` 参数。
            arguments: dict[str, Any] => `arguments` 参数。
            resource_snapshot: dict[str, Any] => `resource_snapshot` 参数。
            policy_id: str => policy ID。
            idempotency_key: str | None => `idempotency_key` 参数。
            ttl_minutes: int => `ttl_minutes` 参数。

        Returns:
            dict[str, Any] => 处理结果。
        """
        key = self.idempotency_key(user_id, action_type, arguments, idempotency_key)
        return self.store.create(
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

    def approve(self, action_id: str, user_id: str) -> dict[str, Any]:
        """处理 `approve` 相关逻辑。

        Args:
            action_id: str => action ID。
            user_id: str => 用户 ID。

        Returns:
            dict[str, Any] => 处理结果。
        """
        action = self.store.get(action_id, user_id)
        if action is None:
            raise KeyError(action_id)
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
        """处理 `reject` 相关逻辑。

        Args:
            action_id: str => action ID。
            user_id: str => 用户 ID。

        Returns:
            dict[str, Any] => 处理结果。
        """
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
        """执行 `execute` 相关数据。

        Args:
            action_id: str => action ID。
            user_id: str => 用户 ID。

        Returns:
            dict[str, Any] => 处理结果。
        """
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
        """处理 `approve_and_execute` 相关逻辑。

        Args:
            action_id: str => action ID。
            user_id: str => 用户 ID。

        Returns:
            dict[str, Any] => 处理结果。
        """
        self.approve(action_id, user_id)
        return self.execute(action_id, user_id)

    def _pending(self, action_id: str, user_id: str) -> dict[str, Any]:
        """处理 `_pending` 相关逻辑。"""
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
