# backend/agent/agent.py

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vllm.config.cache import CacheDType
    from vllm.config.model import ModelDType
    from vllm.model_executor.layers.quantization import QuantizationMethods

from backend.agent.tools.bootstrap import register_builtin_tools
from backend.agent.tools.skills import validate_skill_contracts
from backend.agent.workspaces.models import AgentRunSpec
from backend.core.utils.config import DEBUG_MODE
from backend.core.utils.models import (
    AgentStreamEvent,
    ParsedOutput,
    ToolCall,
)


_UNSUPPORTED_TOOL_CALLS_PATTERN = re.compile(
    r"<[^<>]*tool_calls(?:\s[^<>]*)?>",
    re.IGNORECASE,
)
logger = logging.getLogger(__name__)


def _observed_tools_and_actions(
    messages: list[dict],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
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
    run_spec: AgentRunSpec,
    *,
    mode: str,
    outcome: str,
    started_at: float,
    messages: list[dict],
) -> None:
    tool_names, action_ids = _observed_tools_and_actions(messages)
    logger.info(
        "agent run finished request_id=%s conversation_id=%s workspace=%s "
        "profile=%s profile_fingerprint=%s capability=%s prompt_version=%s "
        "mode=%s outcome=%s latency_ms=%.2f tools=%s action_request_ids=%s",
        run_spec.run_metadata.get("request_id"),
        run_spec.run_metadata.get("conversation_id"),
        run_spec.run_metadata.get("workspace_type"),
        run_spec.run_metadata.get("agent_profile_id"),
        run_spec.run_metadata.get("profile_fingerprint"),
        run_spec.capability_fingerprint,
        run_spec.run_metadata.get("prompt_version"),
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


def sanitize_qwen_history(history: list[dict]) -> list[dict]:
    """移除不属于 Qwen XML 协议的旧工具调用轮次。

    Qwen 使用单数 ``<tool_call>``。旧会话中可能残留复数
    ``<...tool_calls>`` 协议；把它重新放进 prompt 会诱导 Qwen 模仿旧格式。
    删除旧 assistant 调用时，也删除紧随其后的 tool 结果，避免孤立消息。
    """
    sanitized: list[dict] = []
    skip_following_tools = False

    for message in history:
        role = message.get("role")
        content = message.get("content", "")

        if role == "assistant":
            skip_following_tools = isinstance(content, str) and bool(
                _UNSUPPORTED_TOOL_CALLS_PATTERN.search(content)
            )
            if skip_following_tools:
                continue
        elif role == "tool":
            if skip_following_tools:
                continue
        else:
            skip_following_tools = False

        sanitized.append(message)

    return sanitized


class Agent:
    def __init__(
        self,
        model_path: str | Path,
        loop_times: int = 3,
        quantization: QuantizationMethods | None = None,
        dtype: ModelDType = "auto",
        kv_cache_dtype: CacheDType = "auto",
        gpu_memory_utilization: float = 0.95,
        max_model_len: int = 32768,
        max_output_tokens: int = 8192,
        max_num_seqs: int = 1,
        tensor_parallel_size: int = 1,
    ) -> None:
        register_builtin_tools()
        # 在加载昂贵的 vLLM 模型之前 fail-fast，避免 Skill/Tool 漂移带病启动。
        skill_errors = validate_skill_contracts()
        if skill_errors:
            details = "\n".join(f"- {item}" for item in skill_errors)
            raise RuntimeError(f"Skill contract 校验失败:\n{details}")

        # vLLM 保持延迟导入，确保测试/工具脚本可以在未安装 vLLM 时导入 Agent。
        from backend.core.services.vllm_service import LLMProvider

        self.loop_times = loop_times
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
        )

    async def run(self, run_spec: AgentRunSpec) -> list[dict]:
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
        run_spec: AgentRunSpec,
    ) -> list[dict]:
        tool_schemas = [dict(item) for item in run_spec.tool_schemas]
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
                result = await asyncio.wait_for(
                    run_spec.tool_executor.execute(
                        tool_call.name,
                        tool_call.arguments,
                    ),
                    timeout=run_spec.loop_policy.tool_timeout_seconds,
                )
                result_text = serialize_tool_result(result)

                messages.append(
                    {
                        "role": "tool",
                        "name": tool_call.name,
                        "content": result_text,
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

        return new_messages

    async def run_stream(
        self,
        run_spec: AgentRunSpec,
    ) -> AsyncIterator[AgentStreamEvent]:
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
        run_spec: AgentRunSpec,
    ) -> AsyncIterator[AgentStreamEvent]:
        tool_schemas = [dict(item) for item in run_spec.tool_schemas]
        for _ in range(run_spec.loop_policy.max_iterations):
            stream_parser = self.llm_provider.create_stream_parser()

            async for chunk in self.llm_provider.generate_stream(
                messages,
                tool_schemas,
            ):
                for event, delta in stream_parser.feed(chunk):
                    yield AgentStreamEvent(
                        event=event,
                        data={"delta": delta},
                    )

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

            for tool_index, tool_call in enumerate(tool_calls):
                tool_call_id = f"tool-{len(new_messages)}-{tool_index}"
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
                    except TimeoutError:
                        yield AgentStreamEvent(
                            event="tool_progress",
                            data={
                                "id": tool_call_id,
                                "name": tool_call.name,
                            },
                        )
                result_text = serialize_tool_result(result)

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
                        "content": result_text,
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

        yield AgentStreamEvent(
            event="complete",
            data={"messages": new_messages},
        )
