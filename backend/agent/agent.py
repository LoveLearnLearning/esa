# backend/agent/agent.py

"""提供 `agent` 相关功能。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING
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
)


logger = logging.getLogger(__name__)

_TERMINAL_TOOL_ERRORS = frozenset(
    {"tool_not_available", "resource_capability_required"}
)

_KNOWLEDGE_RETRIEVAL_TOOLS = frozenset(
    {
        "retrieve_federated_knowledge",
        "retrieve_personal_knowledge",
        "retrieve_knowledge",
    }
)

_KNOWLEDGE_RESPONSE_CONTRACT = {
    "kind": "evidence_to_explanation",
    "requirements": [
        "先直接回答用户原问题，再解释关键概念及其机制或因果关系",
        "至少给出一个贴合原问题的具体例子；必要时补充边界条件或易错点",
        "只引用与原问题真正相关的证据，并标注其真实来源",
        "证据不足或偏题时明确舍弃该证据，并用通用知识补足讲解",
    ],
    "forbidden": [
        "只摘抄、改写或罗列知识库片段和来源",
        "为了覆盖个人库和公共库而强行使用不相关证据",
        "用‘根据检索结果’开头后立即结束而不解释",
    ],
}

_KNOWLEDGE_MODEL_TOP_LEVEL_KEYS = (
    "ok",
    "error",
    "message",
    "query",
    "result_count",
    "results",
    "sources",
    "degraded",
    "federation",
)

_KNOWLEDGE_MODEL_RESULT_KEYS = (
    "rank",
    "knowledge_scope",
    "source",
    "section",
    "page",
    "content",
)


def _terminal_tool_error(result: object) -> str | None:
    """Return an error that cannot be fixed by retrying tool arguments."""
    if not isinstance(result, Mapping) or result.get("ok") is not False:
        return None
    error = result.get("error")
    return error if isinstance(error, str) and error in _TERMINAL_TOOL_ERRORS else None


def _tool_unavailable_message(name: str, error: str) -> str:
    if error == "resource_capability_required":
        return f"当前请求没有使用工具 `{name}` 所需的资源权限，请重新选择相关附件或资源后再试。"
    return f"当前上下文无法使用工具 `{name}`，请重新选择相关附件或调整问题后再试。"


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


def serialize_tool_result_for_model(name: str, result: object) -> str:
    """Add a trusted answer contract to knowledge observations for the model.

    The persisted/UI-facing Tool result remains the original payload.  This
    model-only envelope keeps retrieval evidence from being mistaken for a
    finished explanation without changing the public Tool contract.
    """

    if name not in _KNOWLEDGE_RETRIEVAL_TOOLS:
        return serialize_tool_result(result)
    if isinstance(result, Mapping):
        payload = {
            key: result[key]
            for key in _KNOWLEDGE_MODEL_TOP_LEVEL_KEYS
            if key in result
        }
        raw_results = result.get("results")
        if isinstance(raw_results, list):
            payload["results"] = [
                {
                    key: item[key]
                    for key in _KNOWLEDGE_MODEL_RESULT_KEYS
                    if key in item
                }
                for item in raw_results
                if isinstance(item, Mapping)
            ]
    else:
        payload = {"result": result}
    payload["_response_contract"] = _KNOWLEDGE_RESPONSE_CONTRACT
    return serialize_tool_result(payload)


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
        lora_path: str | Path | None = None,
        lora_name: str = "esa-agent",
        lora_max_rank: int = 16,
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
            lora_path=lora_path,
            lora_name=lora_name,
            lora_max_rank=lora_max_rank,
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
        stop_loop = False
        for _ in range(run_spec.loop_policy.max_iterations):
            response = await self.llm_provider.generate(
                messages,
                tool_schemas,
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
                assistant_content = parsed.content or response.strip()

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
                result = await asyncio.wait_for(
                    run_spec.tool_executor.execute(
                        tool_call.name,
                        tool_call.arguments,
                    ),
                    timeout=run_spec.loop_policy.tool_timeout_seconds,
                )
                result_text = serialize_tool_result(result)
                model_result_text = serialize_tool_result_for_model(
                    tool_call.name,
                    result,
                )

                messages.append(
                    {
                        "role": "tool",
                        "name": tool_call.name,
                        "content": model_result_text,
                    }
                )
                new_messages.append(
                    {
                        "role": "tool",
                        "name": tool_call.name,
                        "content": result_text,
                        "is_visible": True,
                    }
                )
                terminal_error = _terminal_tool_error(result)
                if terminal_error is not None:
                    terminal_tool_errors[tool_call.name] = terminal_error

            if stop_loop:
                break

        return new_messages

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
        stop_loop = False
        for _ in range(run_spec.loop_policy.max_iterations):
            stream_parser = self.llm_provider.create_stream_parser()
            generation = self.llm_provider.generate_stream(
                messages,
                tool_schemas,
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
                assistant_content = parsed.content or response.strip()
                reasoning = parsed.reasoning or ""

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
                result_text = serialize_tool_result(result)
                model_result_text = serialize_tool_result_for_model(
                    tool_call.name,
                    result,
                )

                tool_message = {
                    "role": "tool",
                    "name": tool_call.name,
                    "content": result_text,
                    "is_visible": True,
                }

                messages.append(
                    {
                        "role": "tool",
                        "name": tool_call.name,
                        "content": model_result_text,
                    }
                )
                new_messages.append(tool_message)

                yield AgentStreamEvent(
                    event="tool",
                    data={
                        "id": tool_call_id,
                        "name": tool_call.name,
                        "content": result_text,
                    },
                )
                terminal_error = _terminal_tool_error(result)
                if terminal_error is not None:
                    terminal_tool_errors[tool_call.name] = terminal_error

            if stop_loop:
                break

        yield AgentStreamEvent(
            event="complete",
            data={"messages": new_messages},
        )
