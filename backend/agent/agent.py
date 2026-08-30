# backend/agent/agent.py

"""提供 `agent` 相关功能。"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

if TYPE_CHECKING:
    from vllm.config.cache import CacheDType
    from vllm.config.model import ModelDType
    from vllm.model_executor.layers.quantization import QuantizationMethods

from backend.agent.tools.bootstrap import register_builtin_tools
from backend.agent.tools.skills import validate_skill_contracts
from backend.agent.workspaces.models import ExecutableAgentRun
from backend.agent.workspaces.history import sanitize_qwen_history as sanitize_qwen_history
from backend.core.utils.config import AGENT_STREAM_HEARTBEAT_SECONDS, DEBUG_MODE
from backend.core.utils.models import (
    AgentStreamEvent,
    ParsedOutput,
    ToolCall,
    ToolExecutionResult,
)
from backend.core.utils.errors import ModelContextOverflow


logger = logging.getLogger(__name__)

_EMPTY_VISIBLE_RESPONSE = "模型本轮未返回可展示正文，请重试。"
_TOOL_SYNTHESIS_FALLBACK = "工具已返回结果，但模型未能形成完整答复，请重试。"

_TERMINAL_TOOL_ERRORS = frozenset(
    {
        "tool_not_available",
        "resource_capability_required",
        "attachment_not_authorized",
    }
)

def _terminal_tool_error(result: object) -> str | None:
    """Return an error that cannot be fixed by retrying tool arguments."""
    if not isinstance(result, Mapping) or result.get("ok") is not False:
        return None
    error = result.get("error")
    return error if isinstance(error, str) and error in _TERMINAL_TOOL_ERRORS else None


def _tool_call_signature(tool_call: ToolCall) -> tuple[str, str]:
    """Return a stable identity for one tool name and its JSON arguments."""

    arguments = json.dumps(
        tool_call.arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return tool_call.name, arguments


def _successful_tool_result(result: object) -> bool:
    """Whether an observation is safe to reuse within the current agent turn."""

    if isinstance(result, Mapping):
        return result.get("ok") is not False and result.get("allowed") is not False
    if isinstance(result, str):
        normalized = result.strip().lower()
        return not (
            normalized.startswith("[error]")
            or normalized.endswith("skill not found!")
        )
    return True


def _tool_unavailable_message(name: str, error: str) -> str:
    if error == "resource_capability_required":
        return f"当前请求没有使用工具 `{name}` 所需的资源权限，请重新选择相关附件或资源后再试。"
    if error == "attachment_not_authorized":
        return f"工具 `{name}` 请求的附件不在当前对话授权清单中，请检查附件是否已删除或是否属于当前对话。"
    return f"当前上下文无法使用工具 `{name}`，请重新选择相关附件或调整问题后再试。"


def _visible_assistant_content(response: str, parsed: ParsedOutput) -> str:
    """Return user-visible content without mistaking reasoning for an answer."""

    if parsed.tool_calls:
        return ""
    if parsed.reasoning is not None:
        remaining = re.sub(
            r"(?:<think>)?.*?</think>",
            "",
            response,
            flags=re.DOTALL | re.IGNORECASE,
        ).strip()
        if not remaining:
            return ""
    return (parsed.content or response).strip()


def _observed_tools_and_actions(
    messages: list[dict],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """处理 `_observed_tools_and_actions` 相关逻辑。"""
    tools: set[str] = set()
    actions: set[str] = set()
    for message in messages:
        if message.get("role") != "tool":
            continue
        name = message.get("name")
        if isinstance(name, str) and name:
            tools.add(name)
        try:
            payload = json.loads(str(message.get("content", "")))
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            action_id = payload.get("action_id")
            if isinstance(action_id, str) and action_id:
                actions.add(action_id)
    return tuple(sorted(tools)), tuple(sorted(actions))


def _log_run_finished(
    run_spec: ExecutableAgentRun,
    *,
    mode: str,
    outcome: str,
    started_at: float,
    messages: list[dict],
) -> None:
    """记录 `run finished` 相关数据。"""
    tool_names, action_ids = _observed_tools_and_actions(messages)
    logger.info(
        "agent run finished run_id=%s request_id=%s conversation_id=%s workspace=%s "
        "definition_version=%s profile=%s profile_fingerprint=%s capability=%s "
        "prompt_version=%s policy_versions=%s resource_revisions=%s "
        "mode=%s outcome=%s latency_ms=%.2f tools=%s action_request_ids=%s",
        run_spec.run_metadata.get("run_id"),
        run_spec.run_metadata.get("request_id"),
        run_spec.run_metadata.get("conversation_id"),
        run_spec.run_metadata.get("workspace_type"),
        run_spec.run_metadata.get("definition_version"),
        run_spec.run_metadata.get("agent_profile_id"),
        run_spec.run_metadata.get("profile_fingerprint"),
        run_spec.capability_fingerprint,
        run_spec.run_metadata.get("prompt_version"),
        run_spec.run_metadata.get("policy_versions"),
        run_spec.run_metadata.get("resource_revisions"),
        mode,
        outcome,
        (time.monotonic() - started_at) * 1000,
        ",".join(tool_names),
        ",".join(action_ids),
    )


def serialize_tool_result(result: object) -> str:
    """将 Tool observation 统一序列化为标准 JSON。

    ``default=str`` 仅用于工具偶发返回 datetime/Path 等可展示但
    不可直接 JSON 化的值，保证传给模型的 observation 始终是合法 JSON。
    """
    return json.dumps(result, ensure_ascii=False, default=str)


def _tool_result_channels(result: object) -> tuple[object, object, object | None]:
    """Normalize legacy single-channel results into the three-channel protocol."""

    if isinstance(result, ToolExecutionResult):
        return result.model_content, result.display_content, result.audit_metadata
    return result, result, None


class Agent:
    """封装 `Agent` 的状态与行为。"""
    def __init__(
        self,
        model_path: str | Path,
        quantization: QuantizationMethods | None = None,
        dtype: ModelDType = "auto",
        kv_cache_dtype: CacheDType = "auto",
        gpu_memory_utilization: float = 0.95,
        max_model_len: int = 32768,
        max_output_tokens: int = 8192,
        max_num_seqs: int = 1,
        tensor_parallel_size: int = 1,
        pipeline_parallel_size: int = 1,
        lora_path: str | Path | None = None,
        lora_name: str = "esa-agent",
        lora_max_rank: int = 16,
        enforce_eager: bool = False,
        performance_mode: Literal[
            "balanced", "interactivity", "throughput"
        ] = "interactivity",
        fully_sharded_loras: bool = False,
        specialize_active_lora: bool = True,
        stream_heartbeat_seconds: float = AGENT_STREAM_HEARTBEAT_SECONDS,
    ) -> None:
        """初始化 `Agent` 实例。"""
        if stream_heartbeat_seconds <= 0:
            raise ValueError("stream_heartbeat_seconds 必须大于 0")
        self.stream_heartbeat_seconds = stream_heartbeat_seconds
        register_builtin_tools()
        # 在加载昂贵的 vLLM 模型之前 fail-fast，避免 Skill/Tool 漂移带病启动。
        skill_errors = validate_skill_contracts()
        if skill_errors:
            details = "\n".join(f"- {item}" for item in skill_errors)
            raise RuntimeError(f"Skill contract 校验失败:\n{details}")

        # vLLM 保持延迟导入，确保测试/工具脚本可以在未安装 vLLM 时导入 Agent。
        from backend.core.services.vllm_service import LLMProvider

        self.llm_provider = LLMProvider(
            model_path=model_path,
            quantization=quantization,
            dtype=dtype,
            kv_cache_dtype=kv_cache_dtype,
            gpu_memory_utilization=gpu_memory_utilization,
            max_model_len=max_model_len,
            max_output_tokens=max_output_tokens,
            max_num_seqs=max_num_seqs,
            tensor_parallel_size=tensor_parallel_size,
            pipeline_parallel_size=pipeline_parallel_size,
            lora_path=lora_path,
            lora_name=lora_name,
            lora_max_rank=lora_max_rank,
            enforce_eager=enforce_eager,
            performance_mode=performance_mode,
            fully_sharded_loras=fully_sharded_loras,
            specialize_active_lora=specialize_active_lora,
        )

    def inspect_prompt(self, run_spec: ExecutableAgentRun):
        """Measure one fully compiled run without invoking the model."""
        return self.llm_provider.inspect_prompt(
            [dict(item) for item in run_spec.messages],
            [dict(item) for item in run_spec.tool_schemas],
        )

    @staticmethod
    def _provider_accepts_metadata(method: object) -> bool:
        """Check whether a test or alternate provider accepts prompt metadata."""

        try:
            parameters = inspect.signature(method).parameters
        except (TypeError, ValueError):
            return False
        return "request_id" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

    async def _generate(
        self,
        messages: list[dict],
        tools: list[dict],
        run_spec: ExecutableAgentRun,
        *,
        generation_index: int = 0,
    ) -> str:
        """Invoke the provider while passing correlation metadata when supported."""

        method = self.llm_provider.generate
        if self._provider_accepts_metadata(method):
            base_request_id = str(run_spec.run_metadata.get("request_id") or "run")
            return await method(
                messages,
                tools,
                request_id=f"{base_request_id}:generation:{generation_index}",
                conversation_id=run_spec.run_metadata.get("conversation_id"),
            )
        return await method(messages, tools)

    def _generate_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        run_spec: ExecutableAgentRun,
        *,
        generation_index: int = 0,
    ) -> AsyncIterator[str]:
        """Invoke streaming generation with optional correlation metadata."""

        method = self.llm_provider.generate_stream
        if self._provider_accepts_metadata(method):
            base_request_id = str(run_spec.run_metadata.get("request_id") or "run")
            return method(
                messages,
                tools,
                request_id=f"{base_request_id}:generation:{generation_index}",
                conversation_id=run_spec.run_metadata.get("conversation_id"),
            )
        return method(messages, tools)

    @staticmethod
    def _append_final_answer(
        messages: list[dict],
        new_messages: list[dict],
        response: str,
        parsed: ParsedOutput,
        *,
        fallback: str,
    ) -> None:
        """Append one visible no-tool answer, with a safe fallback for empty output."""

        assistant_content = _visible_assistant_content(response, parsed)
        # A forced final pass is made with an empty tool list.  If a model still
        # emits a tool protocol block, exposing that block as the answer is
        # confusing and can make the UI appear blank after the loop exits.
        if parsed.tool_calls or not assistant_content:
            assistant_content = fallback
        messages.append({"role": "assistant", "content": assistant_content})
        new_messages.append(
            {
                "role": "assistant",
                "content": assistant_content,
                "reasoning": parsed.reasoning or "",
                "is_visible": True,
            }
        )

    async def run(self, run_spec: ExecutableAgentRun) -> list[dict]:
        """Run one non-streaming turn from an already-authorized specification."""
        started_at = time.monotonic()
        logger.info(
            "agent run started request_id=%s conversation_id=%s workspace=%s profile=%s capability=%s tools=%s",
            run_spec.run_metadata.get("request_id"),
            run_spec.run_metadata.get("conversation_id"),
            run_spec.run_metadata.get("workspace_type"),
            run_spec.run_metadata.get("agent_profile_id"),
            run_spec.capability_fingerprint,
            ",".join(run_spec.run_metadata.get("tool_names", ())),
        )
        messages = [dict(item) for item in run_spec.messages]
        current = messages[-1]
        new_messages = [{**current, "is_visible": True}]
        outcome = "failed"
        try:
            result = await self._run_loop(messages, new_messages, run_spec)
            outcome = "succeeded"
            return result
        finally:
            _log_run_finished(
                run_spec,
                mode="sync",
                outcome=outcome,
                started_at=started_at,
                messages=new_messages,
            )

    async def _run_loop(
        self,
        messages: list[dict],
        new_messages: list[dict],
        run_spec: ExecutableAgentRun,
    ) -> list[dict]:
        """执行 `loop` 相关数据。"""
        tool_schemas = [dict(item) for item in run_spec.tool_schemas]
        terminal_tool_errors: dict[str, str] = {}
        completed_tool_results: dict[tuple[str, str], str] = {}
        stop_loop = False
        needs_final_synthesis = False
        final_generation_index = run_spec.loop_policy.max_iterations
        for iteration in range(run_spec.loop_policy.max_iterations):
            run_spec, messages = await self._fit_context(messages, run_spec)
            tool_schemas = [dict(item) for item in run_spec.tool_schemas]
            response = await self._generate(
                messages,
                tool_schemas,
                run_spec,
                generation_index=iteration,
            )

            parsed: ParsedOutput = self.llm_provider.parse_output(
                response,
                tool_schemas,
            )
            tool_calls: list[ToolCall] = parsed.tool_calls

            if DEBUG_MODE:
                print(f"Thinking: {parsed.reasoning}")
                print(f"Agent: {parsed.content}")

            if not tool_calls:
                assistant_content = (
                    _visible_assistant_content(response, parsed)
                    or _EMPTY_VISIBLE_RESPONSE
                )

                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_content,
                    }
                )
                new_messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_content,
                        "reasoning": parsed.reasoning or "",
                        "is_visible": True,
                    }
                )
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": response,
                }
            )
            new_messages.append(
                {
                    "role": "assistant",
                    "content": response,
                    "is_visible": False,
                }
            )

            executed_tool_call = False
            repeated_successful_call = False
            for tool_call in tool_calls:
                previous_error = terminal_tool_errors.get(tool_call.name)
                if previous_error is not None:
                    assistant_content = _tool_unavailable_message(
                        tool_call.name,
                        previous_error,
                    )
                    messages.append(
                        {"role": "assistant", "content": assistant_content}
                    )
                    new_messages.append(
                        {
                            "role": "assistant",
                            "content": assistant_content,
                            "is_visible": True,
                        }
                    )
                    stop_loop = True
                    break
                signature = _tool_call_signature(tool_call)
                cached_model_text = completed_tool_results.get(signature)
                if cached_model_text is not None:
                    # Keep the model protocol balanced, but do not execute or
                    # display an identical successful operation twice.
                    messages.append(
                        {
                            "role": "tool",
                            "name": tool_call.name,
                            "content": cached_model_text,
                        }
                    )
                    repeated_successful_call = True
                    logger.warning(
                        "agent skipped repeated successful tool call run_id=%s tool=%s",
                        run_spec.run_metadata.get("run_id"),
                        tool_call.name,
                    )
                    continue
                tool_call_id = f"tool-{uuid4().hex}"
                result = await asyncio.wait_for(
                    run_spec.tool_executor.execute(
                        tool_call.name,
                        tool_call.arguments,
                    ),
                    timeout=run_spec.loop_policy.tool_timeout_seconds,
                )
                model_result, display_result, audit_metadata = (
                    _tool_result_channels(result)
                )
                model_text = serialize_tool_result(model_result)
                display_text = serialize_tool_result(display_result)
                executed_tool_call = True

                messages.append(
                    {
                        "role": "tool",
                        "name": tool_call.name,
                        "content": model_text,
                    }
                )
                new_messages.append(
                    {
                        "role": "tool",
                        "name": tool_call.name,
                        "content": display_text,
                        "model_content": model_text,
                        "tool_call_id": tool_call_id,
                        "audit_metadata": audit_metadata,
                        "request_id": run_spec.run_metadata.get("request_id"),
                        "run_id": run_spec.run_metadata.get("run_id"),
                        "is_visible": True,
                    }
                )
                terminal_error = _terminal_tool_error(model_result)
                if terminal_error is not None:
                    terminal_tool_errors[tool_call.name] = terminal_error
                elif _successful_tool_result(model_result):
                    completed_tool_results[signature] = model_text

            if stop_loop:
                break
            if repeated_successful_call and not executed_tool_call:
                needs_final_synthesis = True
                final_generation_index = iteration + 1
                break

        else:
            needs_final_synthesis = True

        if needs_final_synthesis:
            # A repeated successful call or an exhausted loop must still end in
            # one useful answer.  Remove tools for the final synthesis so the
            # model cannot request the same observation again.
            final_response = await self._generate(
                messages,
                [],
                run_spec,
                generation_index=final_generation_index,
            )
            final_parsed = self.llm_provider.parse_output(final_response, [])
            self._append_final_answer(
                messages,
                new_messages,
                final_response,
                final_parsed,
                fallback=_TOOL_SYNTHESIS_FALLBACK,
            )

        return new_messages

    async def _fit_context(
        self,
        messages: list[dict],
        run_spec: ExecutableAgentRun,
    ) -> tuple[ExecutableAgentRun, list[dict]]:
        """Ensure the current dynamic prompt fits the model's real capacity."""
        inspect_prompt = getattr(self.llm_provider, "inspect_prompt", None)
        if not callable(inspect_prompt):
            return run_spec, messages

        while True:
            _prompt, input_tokens, input_limit = inspect_prompt(
                messages,
                [dict(item) for item in run_spec.tool_schemas],
            )
            if input_tokens <= input_limit:
                return run_spec, messages

            compactor = getattr(run_spec.execution_context, "context_compactor", None)
            if not callable(compactor):
                raise ModelContextOverflow(
                    "model context exceeds max_model_len and cannot be compressed"
                )
            refreshed = await compactor()
            if not isinstance(refreshed, ExecutableAgentRun):
                raise ModelContextOverflow(
                    "model context exceeds max_model_len and cannot be compressed"
                )

            last_user = max(
                (index for index, item in enumerate(messages) if item.get("role") == "user"),
                default=-1,
            )
            suffix = messages[last_user + 1 :] if last_user >= 0 else []
            refreshed_messages = [dict(item) for item in refreshed.messages]
            refreshed_messages.extend(dict(item) for item in suffix)
            if refreshed_messages == messages and refreshed.tool_schemas == run_spec.tool_schemas:
                raise ModelContextOverflow(
                    "model context exceeds max_model_len and cannot be compressed"
                )
            run_spec = refreshed
            messages = refreshed_messages

    async def run_stream(
        self,
        run_spec: ExecutableAgentRun,
    ) -> AsyncIterator[AgentStreamEvent]:
        """执行 `stream` 相关数据。

        Args:
            run_spec: AgentRunSpec => `run_spec` 参数。

        Returns:
            AsyncIterator[AgentStreamEvent] => 处理结果。
        """
        started_at = time.monotonic()
        logger.info(
            "agent stream started request_id=%s conversation_id=%s workspace=%s profile=%s capability=%s",
            run_spec.run_metadata.get("request_id"),
            run_spec.run_metadata.get("conversation_id"),
            run_spec.run_metadata.get("workspace_type"),
            run_spec.run_metadata.get("agent_profile_id"),
            run_spec.capability_fingerprint,
        )
        messages = [dict(item) for item in run_spec.messages]
        current = messages[-1]
        new_messages = [{**current, "is_visible": True}]
        outcome = "cancelled"
        try:
            async for event in self._run_stream_loop(messages, new_messages, run_spec):
                yield event
            outcome = "succeeded"
        except Exception:
            outcome = "failed"
            raise
        finally:
            _log_run_finished(
                run_spec,
                mode="stream",
                outcome=outcome,
                started_at=started_at,
                messages=new_messages,
            )

    async def _run_stream_loop(
        self,
        messages: list[dict],
        new_messages: list[dict],
        run_spec: ExecutableAgentRun,
    ) -> AsyncIterator[AgentStreamEvent]:
        """执行 `stream loop` 相关数据。"""
        tool_schemas = [dict(item) for item in run_spec.tool_schemas]
        terminal_tool_errors: dict[str, str] = {}
        completed_tool_results: dict[tuple[str, str], str] = {}
        stop_loop = False
        needs_final_synthesis = False
        final_generation_index = run_spec.loop_policy.max_iterations
        for iteration in range(run_spec.loop_policy.max_iterations):
            run_spec, messages = await self._fit_context(messages, run_spec)
            stream_parser = self.llm_provider.create_stream_parser()
            generation = self._generate_stream(
                messages,
                tool_schemas,
                run_spec,
                generation_index=iteration,
            ).__aiter__()
            pending_chunk: asyncio.Task[str] | None = None
            heartbeat_seconds = getattr(
                self,
                "stream_heartbeat_seconds",
                AGENT_STREAM_HEARTBEAT_SECONDS,
            )
            last_event_at = time.monotonic()

            try:
                while True:
                    if pending_chunk is None:
                        pending_chunk = asyncio.create_task(anext(generation))

                    wait_seconds = max(
                        0.0,
                        heartbeat_seconds - (time.monotonic() - last_event_at),
                    )
                    done, _ = await asyncio.wait(
                        {pending_chunk},
                        timeout=wait_seconds,
                    )
                    if not done:
                        yield AgentStreamEvent(
                            event="heartbeat",
                            data={"stage": "inference"},
                        )
                        last_event_at = time.monotonic()
                        continue

                    try:
                        chunk = pending_chunk.result()
                    except StopAsyncIteration:
                        pending_chunk = None
                        break
                    pending_chunk = None

                    visible_events = stream_parser.feed(chunk)
                    for event, delta in visible_events:
                        yield AgentStreamEvent(
                            event=event,
                            data={"delta": delta},
                        )
                        last_event_at = time.monotonic()

                    # 工具调用 XML 不对用户展示，但模型可能持续生成很久。
                    # 即使 vLLM 一直有隐藏 token，也按 SSE 空闲时间发送心跳。
                    if (
                        not visible_events
                        and time.monotonic() - last_event_at >= heartbeat_seconds
                    ):
                        yield AgentStreamEvent(
                            event="heartbeat",
                            data={"stage": "inference"},
                        )
                        last_event_at = time.monotonic()
            finally:
                if pending_chunk is not None:
                    if not pending_chunk.done():
                        pending_chunk.cancel()
                    with suppress(asyncio.CancelledError, StopAsyncIteration):
                        await pending_chunk
                close_generation = getattr(generation, "aclose", None)
                if close_generation is not None:
                    await close_generation()

            for event, delta in stream_parser.finish():
                yield AgentStreamEvent(
                    event=event,
                    data={"delta": delta},
                )

            response = stream_parser.raw_text
            parsed = self.llm_provider.parse_output(
                response,
                tool_schemas,
            )
            tool_calls = parsed.tool_calls

            if not tool_calls:
                assistant_content = (
                    _visible_assistant_content(response, parsed)
                    or _EMPTY_VISIBLE_RESPONSE
                )
                reasoning = parsed.reasoning or ""

                if assistant_content == _EMPTY_VISIBLE_RESPONSE:
                    yield AgentStreamEvent(
                        event="content",
                        data={"delta": assistant_content},
                    )

                assistant_message = {
                    "role": "assistant",
                    "content": assistant_content,
                    "reasoning": reasoning,
                    "is_visible": True,
                }

                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_content,
                    }
                )
                new_messages.append(assistant_message)
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": response,
                }
            )
            new_messages.append(
                {
                    "role": "assistant",
                    "content": response,
                    "is_visible": False,
                }
            )

            executed_tool_call = False
            repeated_successful_call = False
            for tool_call in tool_calls:
                previous_error = terminal_tool_errors.get(tool_call.name)
                if previous_error is not None:
                    assistant_content = _tool_unavailable_message(
                        tool_call.name,
                        previous_error,
                    )
                    messages.append(
                        {"role": "assistant", "content": assistant_content}
                    )
                    new_messages.append(
                        {
                            "role": "assistant",
                            "content": assistant_content,
                            "is_visible": True,
                        }
                    )
                    yield AgentStreamEvent(
                        event="content",
                        data={"delta": assistant_content},
                    )
                    stop_loop = True
                    break
                signature = _tool_call_signature(tool_call)
                cached_model_text = completed_tool_results.get(signature)
                if cached_model_text is not None:
                    messages.append(
                        {
                            "role": "tool",
                            "name": tool_call.name,
                            "content": cached_model_text,
                        }
                    )
                    repeated_successful_call = True
                    logger.warning(
                        "agent skipped repeated successful tool call run_id=%s tool=%s",
                        run_spec.run_metadata.get("run_id"),
                        tool_call.name,
                    )
                    continue
                tool_call_id = f"tool-{uuid4().hex}"
                yield AgentStreamEvent(
                    event="tool_start",
                    data={
                        "id": tool_call_id,
                        "name": tool_call.name,
                    },
                )
                tool_task = asyncio.create_task(
                    run_spec.tool_executor.execute(
                        tool_call.name,
                        tool_call.arguments,
                    )
                )
                while True:
                    try:
                        result = await asyncio.wait_for(
                            asyncio.shield(tool_task),
                            timeout=run_spec.loop_policy.tool_timeout_seconds,
                        )
                        break
                    except asyncio.TimeoutError:
                        yield AgentStreamEvent(
                            event="tool_progress",
                            data={
                                "id": tool_call_id,
                                "name": tool_call.name,
                            },
                        )
                model_result, display_result, audit_metadata = (
                    _tool_result_channels(result)
                )
                model_text = serialize_tool_result(model_result)
                display_text = serialize_tool_result(display_result)
                executed_tool_call = True

                tool_message = {
                    "role": "tool",
                    "name": tool_call.name,
                    "content": display_text,
                    "model_content": model_text,
                    "tool_call_id": tool_call_id,
                    "audit_metadata": audit_metadata,
                    "request_id": run_spec.run_metadata.get("request_id"),
                    "run_id": run_spec.run_metadata.get("run_id"),
                    "is_visible": True,
                }

                messages.append(
                    {
                        "role": "tool",
                        "name": tool_call.name,
                        "content": model_text,
                    }
                )
                new_messages.append(tool_message)

                yield AgentStreamEvent(
                    event="tool",
                    data={
                        "id": tool_call_id,
                        "name": tool_call.name,
                        "content": display_text,
                    },
                )
                terminal_error = _terminal_tool_error(model_result)
                if terminal_error is not None:
                    terminal_tool_errors[tool_call.name] = terminal_error
                elif _successful_tool_result(model_result):
                    completed_tool_results[signature] = model_text

            if stop_loop:
                break
            if repeated_successful_call and not executed_tool_call:
                needs_final_synthesis = True
                final_generation_index = iteration + 1
                break

        else:
            needs_final_synthesis = True

        if needs_final_synthesis:
            # See the non-streaming loop: force one text-only synthesis after
            # repeated tool calls, and never complete with an empty assistant
            # message.  The forced pass is streamed normally so the Flutter UI
            # receives the same content events as a regular answer.
            stream_parser = self.llm_provider.create_stream_parser()
            generation = self._generate_stream(
                messages,
                [],
                run_spec,
                generation_index=final_generation_index,
            ).__aiter__()
            emitted_content = False
            try:
                async for chunk in generation:
                    for event, delta in stream_parser.feed(chunk):
                        yield AgentStreamEvent(event=event, data={"delta": delta})
                        emitted_content = emitted_content or event == "content"
            finally:
                close_generation = getattr(generation, "aclose", None)
                if close_generation is not None:
                    await close_generation()
            for event, delta in stream_parser.finish():
                yield AgentStreamEvent(event=event, data={"delta": delta})
                emitted_content = emitted_content or event == "content"

            final_response = stream_parser.raw_text
            final_parsed = self.llm_provider.parse_output(final_response, [])
            final_content = _visible_assistant_content(
                final_response,
                final_parsed,
            )
            if not final_content:
                final_content = _TOOL_SYNTHESIS_FALLBACK
            if not emitted_content:
                yield AgentStreamEvent(
                    event="content",
                    data={"delta": final_content},
                )
            messages.append({"role": "assistant", "content": final_content})
            new_messages.append(
                {
                    "role": "assistant",
                    "content": final_content,
                    "reasoning": final_parsed.reasoning or "",
                    "is_visible": True,
                }
            )

        yield AgentStreamEvent(
            event="complete",
            data={"messages": new_messages},
        )
