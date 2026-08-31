# backend/agent/agent.py

"""提供 `agent` 相关功能。"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from vllm.config.cache import CacheDType
    from vllm.config.model import ModelDType
    from vllm.model_executor.layers.quantization import QuantizationMethods

from backend.agent.loop_runtime import (
    AgentLoopRuntime,
    ToolLoopEvent,
    policy_value,
    serialize_tool_result as serialize_tool_result,
    tool_result_channels,
)
from backend.agent.runtime_metrics import AGENT_RUNTIME_METRICS
from backend.agent.tools.bootstrap import register_builtin_tools
from backend.agent.tools.skills import validate_skill_contracts
from backend.agent.workspaces.history import (
    sanitize_qwen_history as sanitize_qwen_history,
)
from backend.agent.workspaces.models import AgentLoopState, ExecutableAgentRun
from backend.core.utils.config import AGENT_STREAM_HEARTBEAT_SECONDS, DEBUG_MODE
from backend.core.utils.errors import ModelContextOverflow
from backend.core.utils.models import AgentStreamEvent, ParsedOutput


logger = logging.getLogger(__name__)

_EMPTY_VISIBLE_RESPONSE = "模型本轮未返回可展示正文，请重试。"
_tool_result_channels = tool_result_channels


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
    state: AgentLoopState,
) -> None:
    """记录 `run finished` 相关数据。"""
    tool_names, action_ids = _observed_tools_and_actions(messages)
    visible_assistants = [
        item
        for item in messages
        if item.get("role") == "assistant" and item.get("is_visible", True)
    ]
    final_answer_empty = (
        not visible_assistants
        or not str(visible_assistants[-1].get("content", "")).strip()
    )
    latency_ms = (time.monotonic() - started_at) * 1000
    AGENT_RUNTIME_METRICS.record(
        workspace=str(run_spec.run_metadata.get("workspace_type") or "unknown"),
        state=state,
        latency_ms=latency_ms,
        final_answer_empty=final_answer_empty,
    )
    logger.info(
        "agent run finished run_id=%s request_id=%s conversation_id=%s workspace=%s "
        "definition_version=%s profile=%s profile_fingerprint=%s capability=%s "
        "prompt_version=%s policy_versions=%s resource_revisions=%s "
        "mode=%s outcome=%s latency_ms=%.2f tools=%s action_request_ids=%s "
        "attempted_tools=%s "
        "max_iterations=%s iterations_used=%s max_tool_calls=%s "
        "tool_attempts=%s retry_count=%s timeout_count=%s error_count=%s "
        "retry_success_count=%s successful_tool_attempts=%s "
        "duplicate_call_count=%s termination_reason=%s "
        "final_synthesis_used=%s final_answer_empty=%s",
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
        latency_ms,
        ",".join(tool_names),
        ",".join(action_ids),
        ",".join(sorted(state.tool_names)),
        policy_value(run_spec.loop_policy, "max_iterations", 1),
        state.iteration,
        policy_value(run_spec.loop_policy, "max_tool_calls", 24),
        state.tool_attempts,
        state.retry_count,
        state.timeout_count,
        state.error_count,
        state.retry_success_count,
        state.successful_tool_attempts,
        state.duplicate_call_count,
        state.termination_reason or "completed",
        state.final_synthesis_used,
        final_answer_empty,
    )


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
        state = AgentLoopState(started_at=started_at)
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
            result = await self._run_loop(messages, new_messages, run_spec, state)
            outcome = "succeeded"
            return result
        except asyncio.CancelledError:
            state.termination_reason = "cancelled"
            outcome = "cancelled"
            raise
        finally:
            _log_run_finished(
                run_spec,
                mode="sync",
                outcome=outcome,
                started_at=started_at,
                messages=new_messages,
                state=state,
            )

    @staticmethod
    def _append_tool_observation(
        messages: list[dict],
        new_messages: list[dict],
        run_spec: ExecutableAgentRun,
        event: ToolLoopEvent,
    ) -> None:
        """Append balanced model/display/audit projections for one tool call."""

        observation = event.observation
        assert observation is not None
        assert event.tool_call_id is not None
        messages.append(
            {
                "role": "tool",
                "name": event.tool_call.name,
                "content": observation.model_text,
            }
        )
        new_messages.append(
            {
                "role": "tool",
                "name": event.tool_call.name,
                "content": observation.display_text,
                "model_content": observation.model_text,
                "tool_call_id": event.tool_call_id,
                "audit_metadata": observation.audit_metadata,
                "request_id": run_spec.run_metadata.get("request_id"),
                "run_id": run_spec.run_metadata.get("run_id"),
                "is_visible": True,
            }
        )

    async def _run_loop(
        self,
        messages: list[dict],
        new_messages: list[dict],
        run_spec: ExecutableAgentRun,
        state: AgentLoopState,
    ) -> list[dict]:
        """Run the bounded non-streaming model/tool loop."""
        tool_schemas = [dict(item) for item in run_spec.tool_schemas]
        runtime = AgentLoopRuntime(run_spec.loop_policy, state)

        while (generation_index := runtime.begin_iteration()) is not None:
            remaining = runtime.remaining_time()
            try:
                run_spec, messages = await asyncio.wait_for(
                    self._fit_context(messages, run_spec), timeout=remaining
                )
                tool_schemas = [dict(item) for item in run_spec.tool_schemas]
                remaining = runtime.remaining_time()
                if remaining <= 0:
                    runtime.terminate("wall_time_limit")
                    break
                response = await asyncio.wait_for(
                    self._generate(
                        messages,
                        tool_schemas,
                        run_spec,
                        generation_index=generation_index,
                    ),
                    timeout=remaining,
                )
                parsed: ParsedOutput = self.llm_provider.parse_output(
                    response, tool_schemas
                )
            except ModelContextOverflow:
                logger.exception("agent context overflow")
                runtime.terminate("context_overflow")
                break
            except asyncio.TimeoutError:
                runtime.terminate("wall_time_limit")
                break
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - model boundary
                logger.exception("agent model generation failed")
                runtime.terminate("model_error")
                break
            tool_calls = parsed.tool_calls

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
                        "termination_reason": "completed",
                    }
                )
                runtime.complete()
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

            async for event in runtime.process_tool_calls(run_spec, tool_calls):
                if event.kind == "reuse":
                    assert event.cached_model_text is not None
                    messages.append(
                        {
                            "role": "tool",
                            "name": event.tool_call.name,
                            "content": event.cached_model_text,
                        }
                    )
                    continue
                if event.kind == "observation":
                    self._append_tool_observation(
                        messages,
                        new_messages,
                        run_spec,
                        event,
                    )

        if state.termination_reason != "completed":
            finalization = runtime.finalization_plan()
            fallback = finalization.fallback
            if finalization.should_synthesize:
                try:
                    final_response = await asyncio.wait_for(
                        self._generate(
                            messages,
                            [],
                            run_spec,
                            generation_index=finalization.generation_index,
                        ),
                        timeout=finalization.remaining_seconds,
                    )
                    final_parsed = self.llm_provider.parse_output(final_response, [])
                    self._append_final_answer(
                        messages,
                        new_messages,
                        final_response,
                        final_parsed,
                        fallback=fallback,
                    )
                except asyncio.TimeoutError:
                    runtime.terminate("wall_time_limit")
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - best-effort synthesis
                    logger.exception("agent final synthesis failed")
            if not any(
                item.get("role") == "assistant" and item.get("is_visible")
                for item in new_messages
            ):
                fallback = runtime.fallback_message()
                messages.append({"role": "assistant", "content": fallback})
                new_messages.append(
                    {
                        "role": "assistant",
                        "content": fallback,
                        "reasoning": "",
                        "is_visible": True,
                    }
                )
            new_messages[-1]["termination_reason"] = state.termination_reason

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
                (
                    index
                    for index, item in enumerate(messages)
                    if item.get("role") == "user"
                ),
                default=-1,
            )
            suffix = messages[last_user + 1 :] if last_user >= 0 else []
            refreshed_messages = [dict(item) for item in refreshed.messages]
            refreshed_messages.extend(dict(item) for item in suffix)
            if (
                refreshed_messages == messages
                and refreshed.tool_schemas == run_spec.tool_schemas
            ):
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
        state = AgentLoopState(started_at=started_at)
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
            async for event in self._run_stream_loop(
                messages, new_messages, run_spec, state
            ):
                yield event
            outcome = "succeeded"
        except asyncio.CancelledError:
            state.termination_reason = "cancelled"
            raise
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
                state=state,
            )

    async def _run_stream_loop(
        self,
        messages: list[dict],
        new_messages: list[dict],
        run_spec: ExecutableAgentRun,
        state: AgentLoopState,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Run the streaming loop with the same budgets as the sync path."""
        tool_schemas = [dict(item) for item in run_spec.tool_schemas]
        runtime = AgentLoopRuntime(run_spec.loop_policy, state)
        heartbeat_seconds = getattr(
            self,
            "stream_heartbeat_seconds",
            AGENT_STREAM_HEARTBEAT_SECONDS,
        )

        while (generation_index := runtime.begin_iteration()) is not None:
            remaining = runtime.remaining_time()
            try:
                run_spec, messages = await asyncio.wait_for(
                    self._fit_context(messages, run_spec), timeout=remaining
                )
            except ModelContextOverflow:
                logger.exception("streaming agent context overflow")
                runtime.terminate("context_overflow")
                break
            except asyncio.TimeoutError:
                runtime.terminate("wall_time_limit")
                break
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - context/model boundary
                logger.exception("streaming agent context preparation failed")
                runtime.terminate("model_error")
                break

            tool_schemas = [dict(item) for item in run_spec.tool_schemas]
            stream_parser = self.llm_provider.create_stream_parser()
            generation = self._generate_stream(
                messages,
                tool_schemas,
                run_spec,
                generation_index=generation_index,
            ).__aiter__()
            pending_chunk: asyncio.Task[str] | None = None
            last_event_at = time.monotonic()

            try:
                while True:
                    remaining = runtime.remaining_time()
                    if remaining <= 0:
                        runtime.terminate("wall_time_limit")
                        break
                    if pending_chunk is None:
                        pending_chunk = asyncio.create_task(anext(generation))

                    wait_seconds = min(
                        remaining,
                        max(
                            0.0,
                            heartbeat_seconds - (time.monotonic() - last_event_at),
                        ),
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
                    except asyncio.CancelledError:
                        raise
                    except Exception:  # noqa: BLE001 - provider boundary
                        logger.exception("streaming model generation failed")
                        runtime.terminate("model_error")
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
                    with suppress(Exception):
                        await close_generation()

            if state.termination_reason is not None:
                break

            try:
                for event, delta in stream_parser.finish():
                    yield AgentStreamEvent(event=event, data={"delta": delta})
                response = stream_parser.raw_text
                parsed = self.llm_provider.parse_output(response, tool_schemas)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - parser boundary
                logger.exception("streaming model response parsing failed")
                runtime.terminate("model_error")
                break
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
                    "termination_reason": "completed",
                }

                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_content,
                    }
                )
                new_messages.append(assistant_message)
                runtime.complete()
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

            async for event in runtime.process_tool_calls(
                run_spec,
                tool_calls,
                progress_interval=heartbeat_seconds,
            ):
                if event.kind == "reuse":
                    assert event.cached_model_text is not None
                    messages.append(
                        {
                            "role": "tool",
                            "name": event.tool_call.name,
                            "content": event.cached_model_text,
                        }
                    )
                    continue
                assert event.tool_call_id is not None
                if event.kind == "start":
                    yield AgentStreamEvent(
                        event="tool_start",
                        data={
                            "id": event.tool_call_id,
                            "name": event.tool_call.name,
                        },
                    )
                    continue
                if event.kind == "progress":
                    yield AgentStreamEvent(
                        event="tool_progress",
                        data={
                            "id": event.tool_call_id,
                            "name": event.tool_call.name,
                        },
                    )
                    continue
                observation = event.observation
                assert observation is not None
                self._append_tool_observation(
                    messages,
                    new_messages,
                    run_spec,
                    event,
                )
                if observation.is_error:
                    yield AgentStreamEvent(
                        event="tool_error",
                        data={
                            "id": event.tool_call_id,
                            "name": event.tool_call.name,
                            "content": observation.display_text,
                        },
                    )
                yield AgentStreamEvent(
                    event="tool",
                    data={
                        "id": event.tool_call_id,
                        "name": event.tool_call.name,
                        "content": observation.display_text,
                    },
                )

        if state.termination_reason != "completed":
            finalization = runtime.finalization_plan()
            fallback = finalization.fallback
            final_content: str | None = None
            final_reasoning = ""
            emitted_content = False
            if finalization.should_synthesize:
                stream_parser = self.llm_provider.create_stream_parser()
                generation = self._generate_stream(
                    messages,
                    [],
                    run_spec,
                    generation_index=finalization.generation_index,
                ).__aiter__()
                pending_chunk: asyncio.Task[str] | None = None
                synthesis_failed = False
                try:
                    while True:
                        remaining = runtime.remaining_time()
                        if remaining <= 0:
                            runtime.terminate("wall_time_limit")
                            synthesis_failed = True
                            break
                        if pending_chunk is None:
                            pending_chunk = asyncio.create_task(anext(generation))
                        done, _ = await asyncio.wait(
                            {pending_chunk},
                            timeout=min(heartbeat_seconds, remaining),
                        )
                        if not done:
                            yield AgentStreamEvent(
                                event="heartbeat", data={"stage": "synthesis"}
                            )
                            continue
                        try:
                            chunk = pending_chunk.result()
                        except StopAsyncIteration:
                            pending_chunk = None
                            break
                        except asyncio.CancelledError:
                            raise
                        except Exception:  # noqa: BLE001 - provider boundary
                            logger.exception("streaming final synthesis failed")
                            pending_chunk = None
                            synthesis_failed = True
                            break
                        pending_chunk = None
                        for event, delta in stream_parser.feed(chunk):
                            yield AgentStreamEvent(event=event, data={"delta": delta})
                            emitted_content = emitted_content or event == "content"
                finally:
                    if pending_chunk is not None and not pending_chunk.done():
                        pending_chunk.cancel()
                        with suppress(asyncio.CancelledError, StopAsyncIteration):
                            await pending_chunk
                    close_generation = getattr(generation, "aclose", None)
                    if close_generation is not None:
                        with suppress(Exception):
                            await close_generation()

                if not synthesis_failed:
                    try:
                        for event, delta in stream_parser.finish():
                            yield AgentStreamEvent(event=event, data={"delta": delta})
                            emitted_content = emitted_content or event == "content"
                        final_response = stream_parser.raw_text
                        final_parsed = self.llm_provider.parse_output(
                            final_response, []
                        )
                        final_content = _visible_assistant_content(
                            final_response, final_parsed
                        )
                        final_reasoning = final_parsed.reasoning or ""
                        if final_parsed.tool_calls:
                            final_content = None
                    except Exception:  # noqa: BLE001 - best-effort synthesis
                        logger.exception("streaming final synthesis parsing failed")

            if not final_content:
                final_content = runtime.fallback_message()
            if not emitted_content or final_content == fallback:
                yield AgentStreamEvent(event="content", data={"delta": final_content})
            messages.append({"role": "assistant", "content": final_content})
            new_messages.append(
                {
                    "role": "assistant",
                    "content": final_content,
                    "reasoning": final_reasoning,
                    "is_visible": True,
                    "termination_reason": state.termination_reason,
                }
            )

        metadata = runtime.metadata()
        yield AgentStreamEvent(
            event="complete",
            data={
                "messages": new_messages,
                "termination_reason": state.termination_reason,
                "run_metadata": {**dict(run_spec.run_metadata), **metadata},
            },
        )
