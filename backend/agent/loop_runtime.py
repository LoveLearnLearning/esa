"""Deterministic budget, retry, and tool-batch control for one Agent turn."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from backend.agent.tools.catalog import (
    TRANSIENT_TOOL_ERRORS,
    capability_declaration,
)
from backend.agent.tools.execution_errors import (
    classify_tool_exception,
    normalize_tool_error_result,
    structured_tool_error,
    tool_error_payload,
)
from backend.agent.workspaces.models import AgentLoopState, ExecutableAgentRun
from backend.core.utils.models import ToolCall, ToolExecutionResult


logger = logging.getLogger(__name__)

ToolEventKind = Literal["start", "progress", "reuse", "observation"]


@dataclass(frozen=True, slots=True)
class ToolObservation:
    """Three-channel result of one executed or runtime-rejected tool call."""

    model_result: object
    model_text: str
    display_text: str
    audit_metadata: object | None
    attempt: int
    is_error: bool


@dataclass(frozen=True, slots=True)
class ToolLoopEvent:
    """Transport-neutral event emitted while processing a tool batch."""

    kind: ToolEventKind
    tool_call: ToolCall
    tool_call_id: str | None = None
    observation: ToolObservation | None = None
    cached_model_text: str | None = None


@dataclass(frozen=True, slots=True)
class FinalizationPlan:
    """Decision for the one optional, tool-free final synthesis pass."""

    should_synthesize: bool
    remaining_seconds: float
    generation_index: int
    fallback: str


@dataclass(frozen=True, slots=True)
class _ToolAttemptOutcome:
    result: object
    attempt: int
    termination_reason: str | None = None


def serialize_tool_result(result: object) -> str:
    """Serialize a tool observation as model-safe JSON."""

    return json.dumps(result, ensure_ascii=False, default=str)


def retry_delay(retry_count: int) -> float:
    """Return bounded exponential backoff with a small jitter."""

    return min(8.0, 0.5 * (2**retry_count)) + random.uniform(0.0, 0.25)


def policy_value(policy: object, name: str, default: object) -> object:
    """Read current policy fields while accepting legacy run specifications."""

    return getattr(policy, name, default)


def _tool_call_signature(tool_call: ToolCall) -> tuple[str, str]:
    arguments = json.dumps(
        tool_call.arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return tool_call.name, arguments


def _signature_key(signature: tuple[str, str]) -> str:
    return f"{signature[0]}:{signature[1]}"


def _successful_tool_result(result: object) -> bool:
    if isinstance(result, Mapping):
        return result.get("ok") is not False and result.get("allowed") is not False
    if isinstance(result, str):
        normalized = result.strip().lower()
        return not (
            normalized.startswith("[error]") or normalized.endswith("skill not found!")
        )
    return True


def _tool_policy(executor: object, name: str) -> object | None:
    resolver = getattr(executor, "policy_for", None)
    if callable(resolver):
        try:
            return resolver(name)
        except (KeyError, ValueError):
            return None
    try:
        return capability_declaration(name)
    except ValueError:
        return None


def _tool_timeout(policy: object, tool_policy: object | None) -> float:
    configured = float(policy_value(policy, "tool_timeout_seconds", 30.0))
    declared = getattr(tool_policy, "default_timeout_seconds", None)
    if isinstance(declared, (int, float)) and declared > 0:
        return min(configured, float(declared))
    return configured


def _tool_retry_limit(policy: object, tool_policy: object | None) -> int:
    configured = int(policy_value(policy, "max_retries_per_tool", 1))
    declared = getattr(tool_policy, "max_retries", None)
    if isinstance(declared, int) and declared >= 0:
        return min(configured, declared)
    return configured


def _automatic_retry_allowed(
    tool_policy: object | None,
    arguments: Mapping[str, object],
    error_code: str,
) -> bool:
    if tool_policy is None:
        return False
    retryable_errors = getattr(tool_policy, "retryable_errors", TRANSIENT_TOOL_ERRORS)
    if error_code not in retryable_errors:
        return False
    if bool(getattr(tool_policy, "read_only", False)):
        return True
    return bool(
        getattr(tool_policy, "idempotent", False)
        and getattr(tool_policy, "supports_idempotency_key", False)
        and arguments.get("idempotency_key")
    )


def tool_result_channels(result: object) -> tuple[object, object, object | None]:
    if isinstance(result, ToolExecutionResult):
        return result.model_content, result.display_content, result.audit_metadata
    return result, result, None


class AgentLoopRuntime:
    """Own the deterministic state machine shared by sync and stream adapters."""

    def __init__(self, policy: object, state: AgentLoopState) -> None:
        self.policy = policy
        self.state = state
        self.deadline = state.started_at + float(
            policy_value(policy, "max_wall_time_seconds", 240.0)
        )
        self.max_iterations = int(policy_value(policy, "max_iterations", 1))
        self.max_tool_calls = int(policy_value(policy, "max_tool_calls", 24))
        self.max_same_repeats = int(policy_value(policy, "max_same_call_repeats", 2))
        self._completed_tool_results: dict[tuple[str, str], str] = {}
        self._failed_call_counts: dict[tuple[str, str], int] = {}

    def remaining_time(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def terminate(self, reason: str) -> None:
        self.state.termination_reason = reason

    def complete(self) -> None:
        self.terminate("completed")

    def begin_iteration(self) -> int | None:
        """Admit one model generation and return its zero-based index."""

        if self.state.termination_reason is not None:
            return None
        if self.state.iteration >= self.max_iterations:
            self.terminate("iteration_limit")
            return None
        if self.remaining_time() <= 0:
            self.terminate("wall_time_limit")
            return None
        generation_index = self.state.iteration
        self.state.iteration += 1
        return generation_index

    async def process_tool_calls(
        self,
        run_spec: ExecutableAgentRun,
        tool_calls: Sequence[ToolCall],
        *,
        progress_interval: float | None = None,
    ) -> AsyncIterator[ToolLoopEvent]:
        """Process one model-produced tool batch under the shared loop policy."""

        executed_tool_call = False
        repeated_successful_call = False

        for call_index, tool_call in enumerate(tool_calls):
            signature = _tool_call_signature(tool_call)
            signature_key = _signature_key(signature)
            self.state.repeated_calls[signature_key] = (
                self.state.repeated_calls.get(signature_key, 0) + 1
            )

            cached_model_text = self._completed_tool_results.get(signature)
            if cached_model_text is not None:
                repeated_successful_call = True
                self.state.duplicate_call_count += 1
                logger.warning(
                    "agent skipped repeated successful tool call run_id=%s tool=%s",
                    run_spec.run_metadata.get("run_id"),
                    tool_call.name,
                )
                yield ToolLoopEvent(
                    kind="reuse",
                    tool_call=tool_call,
                    cached_model_text=cached_model_text,
                )
                continue

            if self._failed_call_counts.get(signature, 0) >= self.max_same_repeats:
                self.state.duplicate_call_count += 1
                self.state.error_count += 1
                self.state.failed_tool_names.add(tool_call.name)
                blocked = structured_tool_error(
                    "duplicate_call_blocked",
                    tool=tool_call.name,
                    retryable=False,
                    request_id=run_spec.run_metadata.get("request_id"),
                    run_id=run_spec.run_metadata.get("run_id"),
                )
                yield self._observation_event(
                    run_spec,
                    tool_call,
                    blocked,
                    attempt=1,
                )
                self.terminate("duplicate_call_limit")
                break

            if self.state.tool_attempts >= self.max_tool_calls:
                for pending_call in tool_calls[call_index:]:
                    self.state.error_count += 1
                    self.state.failed_tool_names.add(pending_call.name)
                    exhausted = structured_tool_error(
                        "tool_budget_exhausted",
                        tool=pending_call.name,
                        retryable=False,
                        request_id=run_spec.run_metadata.get("request_id"),
                        run_id=run_spec.run_metadata.get("run_id"),
                    )
                    yield self._observation_event(
                        run_spec,
                        pending_call,
                        exhausted,
                        attempt=1,
                    )
                self.terminate("tool_call_limit")
                break

            tool_call_id = f"tool-{uuid4().hex}"
            if progress_interval is not None:
                yield ToolLoopEvent(
                    kind="start",
                    tool_call=tool_call,
                    tool_call_id=tool_call_id,
                )
                execution_task = asyncio.create_task(
                    self._execute_tool(run_spec, tool_call, signature_key)
                )
                try:
                    while not execution_task.done():
                        remaining = self.remaining_time()
                        if remaining <= 0:
                            execution_task.cancel()
                            try:
                                await execution_task
                            except asyncio.CancelledError:
                                pass
                            outcome = _ToolAttemptOutcome(
                                result=structured_tool_error(
                                    "wall_time_exhausted",
                                    tool=tool_call.name,
                                    retryable=False,
                                    request_id=run_spec.run_metadata.get("request_id"),
                                    run_id=run_spec.run_metadata.get("run_id"),
                                ),
                                attempt=1,
                                termination_reason="wall_time_limit",
                            )
                            break
                        done, _ = await asyncio.wait(
                            {execution_task},
                            timeout=min(progress_interval, remaining),
                        )
                        if done:
                            outcome = execution_task.result()
                            break
                        yield ToolLoopEvent(
                            kind="progress",
                            tool_call=tool_call,
                            tool_call_id=tool_call_id,
                        )
                    else:
                        outcome = execution_task.result()
                except asyncio.CancelledError:
                    if not execution_task.done():
                        execution_task.cancel()
                    try:
                        await execution_task
                    except asyncio.CancelledError:
                        pass
                    raise
            else:
                outcome = await self._execute_tool(
                    run_spec,
                    tool_call,
                    signature_key,
                )

            executed_tool_call = True
            observation_event = self._observation_event(
                run_spec,
                tool_call,
                outcome.result,
                attempt=outcome.attempt,
                tool_call_id=tool_call_id,
            )
            observation = observation_event.observation
            assert observation is not None
            if _successful_tool_result(observation.model_result):
                self._completed_tool_results[signature] = observation.model_text
            else:
                self._failed_call_counts[signature] = (
                    self._failed_call_counts.get(signature, 0) + 1
                )
            yield observation_event
            if outcome.termination_reason is not None:
                self.terminate(outcome.termination_reason)
                break

        if repeated_successful_call and not executed_tool_call:
            self.terminate("duplicate_call_limit")

    async def _execute_tool(
        self,
        run_spec: ExecutableAgentRun,
        tool_call: ToolCall,
        signature_key: str,
    ) -> _ToolAttemptOutcome:
        catalog_policy = _tool_policy(run_spec.tool_executor, tool_call.name)
        retry_limit = _tool_retry_limit(self.policy, catalog_policy)
        attempt = 0

        while True:
            if self.state.tool_attempts >= self.max_tool_calls:
                next_attempt = max(1, attempt + 1)
                return _ToolAttemptOutcome(
                    structured_tool_error(
                        "tool_budget_exhausted",
                        tool=tool_call.name,
                        attempt=next_attempt,
                        retryable=False,
                        request_id=run_spec.run_metadata.get("request_id"),
                        run_id=run_spec.run_metadata.get("run_id"),
                    ),
                    next_attempt,
                    "tool_call_limit",
                )
            remaining = self.remaining_time()
            if remaining <= 0:
                next_attempt = max(1, attempt + 1)
                return _ToolAttemptOutcome(
                    structured_tool_error(
                        "wall_time_exhausted",
                        tool=tool_call.name,
                        attempt=next_attempt,
                        retryable=False,
                        request_id=run_spec.run_metadata.get("request_id"),
                        run_id=run_spec.run_metadata.get("run_id"),
                    ),
                    next_attempt,
                    "wall_time_limit",
                )

            attempt += 1
            self.state.tool_attempts += 1
            self.state.tool_names.add(tool_call.name)
            timeout = min(_tool_timeout(self.policy, catalog_policy), remaining)
            attempt_started = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    run_spec.tool_executor.execute(tool_call.name, tool_call.arguments),
                    timeout=timeout,
                )
            except asyncio.TimeoutError as error:
                result = structured_tool_error(
                    "timeout",
                    tool=tool_call.name,
                    attempt=attempt,
                    retryable=True,
                    retry_after_ms=1000,
                    request_id=run_spec.run_metadata.get("request_id"),
                    run_id=run_spec.run_metadata.get("run_id"),
                    elapsed_ms=(time.monotonic() - attempt_started) * 1000,
                    exception=error,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - executor boundary
                error_code, retryable, retry_after_ms = classify_tool_exception(error)
                logger.exception(
                    "tool executor escaped its error boundary run_id=%s tool=%s",
                    run_spec.run_metadata.get("run_id"),
                    tool_call.name,
                )
                result = structured_tool_error(
                    error_code,
                    tool=tool_call.name,
                    attempt=attempt,
                    retryable=retryable,
                    retry_after_ms=retry_after_ms,
                    request_id=run_spec.run_metadata.get("request_id"),
                    run_id=run_spec.run_metadata.get("run_id"),
                    elapsed_ms=(time.monotonic() - attempt_started) * 1000,
                    exception=error,
                )

            result = normalize_tool_error_result(
                result,
                tool=tool_call.name,
                attempt=attempt,
                request_id=run_spec.run_metadata.get("request_id"),
                run_id=run_spec.run_metadata.get("run_id"),
                elapsed_ms=(time.monotonic() - attempt_started) * 1000,
            )
            error_payload = tool_error_payload(result)
            if error_payload is None:
                self.state.successful_tool_attempts += 1
                if attempt > 1:
                    self.state.retry_success_count += 1
                return _ToolAttemptOutcome(result, attempt)

            self.state.error_count += 1
            self.state.failed_tool_names.add(tool_call.name)
            error_code = str(
                error_payload.get("error_code")
                or error_payload.get("error")
                or "tool_internal_error"
            )
            if error_code == "timeout":
                self.state.timeout_count += 1
            retryable = bool(error_payload.get("retryable"))
            can_retry = retryable and _automatic_retry_allowed(
                catalog_policy, tool_call.arguments, error_code
            )
            retries_used = attempt - 1
            if not retryable:
                return _ToolAttemptOutcome(result, attempt, "terminal_tool_error")
            if not can_retry:
                return _ToolAttemptOutcome(result, attempt)
            if retries_used >= retry_limit:
                return _ToolAttemptOutcome(result, attempt, "retry_limit")
            if self.state.tool_attempts >= self.max_tool_calls:
                return _ToolAttemptOutcome(result, attempt, "tool_call_limit")

            delay = retry_delay(retries_used)
            if self.remaining_time() <= delay:
                return _ToolAttemptOutcome(result, attempt, "wall_time_limit")
            await asyncio.sleep(delay)
            self.state.retry_counts[signature_key] = (
                self.state.retry_counts.get(signature_key, 0) + 1
            )

    def _observation_event(
        self,
        run_spec: ExecutableAgentRun,
        tool_call: ToolCall,
        result: object,
        *,
        attempt: int,
        tool_call_id: str | None = None,
    ) -> ToolLoopEvent:
        normalized = normalize_tool_error_result(
            result,
            tool=tool_call.name,
            attempt=attempt,
            request_id=run_spec.run_metadata.get("request_id"),
            run_id=run_spec.run_metadata.get("run_id"),
        )
        model_result, display_result, audit_metadata = tool_result_channels(normalized)
        return ToolLoopEvent(
            kind="observation",
            tool_call=tool_call,
            tool_call_id=tool_call_id or f"tool-{uuid4().hex}",
            observation=ToolObservation(
                model_result=model_result,
                model_text=serialize_tool_result(model_result),
                display_text=serialize_tool_result(display_result),
                audit_metadata=audit_metadata,
                attempt=attempt,
                is_error=tool_error_payload(model_result) is not None,
            ),
        )

    def finalization_plan(self) -> FinalizationPlan:
        if self.state.termination_reason is None:
            self.terminate("iteration_limit")
        remaining = self.remaining_time()
        should_synthesize = (
            self.state.termination_reason not in {"completed", "wall_time_limit"}
            and remaining > 0
        )
        if should_synthesize:
            self.state.final_synthesis_used = True
        return FinalizationPlan(
            should_synthesize=should_synthesize,
            remaining_seconds=remaining,
            generation_index=self.state.iteration,
            fallback=self.fallback_message(),
        )

    def fallback_message(self) -> str:
        reason_messages = {
            "iteration_limit": "已达到本轮模型循环预算",
            "tool_call_limit": "本轮工具调用预算已用完",
            "retry_limit": "工具自动重试已达到上限",
            "wall_time_limit": "本轮处理已达到最长运行时间",
            "duplicate_call_limit": "相同失败工具调用已达到重复上限",
            "terminal_tool_error": "工具遇到不可恢复的错误",
            "model_error": "模型生成暂时失败",
            "context_overflow": "当前上下文过长且无法继续压缩",
            "cancelled": "本轮请求已取消",
        }
        reason = reason_messages.get(
            self.state.termination_reason or "", "本轮处理已结束"
        )
        parts = [f"已取得 {self.state.successful_tool_attempts} 次有效工具结果"]
        if self.state.error_count:
            parts.append(f"有 {self.state.error_count} 次工具尝试失败")
        if self.state.failed_tool_names:
            parts.append("涉及工具：" + "、".join(sorted(self.state.failed_tool_names)))
        parts.append(reason)
        return (
            "，".join(parts)
            + "。下面只能基于已取得的信息给出阶段性结论；如需继续查证，请缩小问题范围后重试。"
        )

    def metadata(self) -> dict[str, object]:
        return {
            "termination_reason": self.state.termination_reason or "completed",
            "max_iterations": self.max_iterations,
            "iterations_used": self.state.iteration,
            "max_tool_calls": self.max_tool_calls,
            "tool_attempts": self.state.tool_attempts,
            "retry_count": self.state.retry_count,
            "retry_success_count": self.state.retry_success_count,
            "tool_names": sorted(self.state.tool_names),
            "timeout_count": self.state.timeout_count,
            "error_count": self.state.error_count,
            "successful_tool_attempts": self.state.successful_tool_attempts,
            "duplicate_call_count": self.state.duplicate_call_count,
            "final_synthesis_used": self.state.final_synthesis_used,
            "total_latency_ms": (time.monotonic() - self.state.started_at) * 1000,
        }
