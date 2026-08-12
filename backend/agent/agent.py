# backend/agent/agent.py

from __future__ import annotations

import asyncio
import json
import re
from contextlib import nullcontext
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vllm.config.cache import CacheDType
    from vllm.config.model import ModelDType
    from vllm.model_executor.layers.quantization import QuantizationMethods

from backend.agent.learning.pedagogy_router import PedagogyRouter
from backend.agent.tools import tr
from backend.agent.tools.attachment_tools import (
    AttachmentToolContext,
    attachment_tool_context,
)
from backend.agent.tools.mastery_tools import set_current_total_weeks
from backend.agent.tools.memory_tools import (
    set_current_conversation_mode,
    set_current_user,
)
from backend.agent.tools.skills import (
    build_autoload_skills_context,
    build_skills_context,
    load_skill,
    validate_skill_contracts,
)
from backend.core.message.build_prompt import build_system_prompt
from backend.core.utils.config import DEBUG_MODE
from backend.core.utils.models import (
    AgentStreamEvent,
    ParsedOutput,
    PromptContext,
    ToolCall,
    UserRecord,
)


_UNSUPPORTED_TOOL_CALLS_PATTERN = re.compile(
    r"<[^<>]*tool_calls(?:\s[^<>]*)?>",
    re.IGNORECASE,
)

_LEARNING_ONLY_TOOLS = frozenset(
    {
        "save_core_memory",
        "search_core_memories",
        "get_core_memories",
        "delete_core_memory",
        "recommend_practice",
        "get_mastery_report",
        "get_mastery_level",
        "get_weak_prerequisites",
        "get_review_timing",
        "record_answer",
        "record_learning_evidence",
        "get_learning_evidence_summary",
        "retrieve_knowledge",
        "get_knowledge_base_stats",
    }
)


def tool_schemas_for_workspace(workspace_type: str) -> list[dict]:
    """Return only tools whose state and semantics belong to this workspace."""
    if workspace_type == "learning":
        return tr.schemas
    return [
        schema
        for schema in tr.schemas
        if schema["function"]["name"] not in _LEARNING_ONLY_TOOLS
    ]


async def call_workspace_tool_async(
    workspace_type: str,
    name: str,
    arguments: dict,
) -> object:
    if workspace_type != "learning" and name in _LEARNING_ONLY_TOOLS:
        return f"[Error]: tool {name!r} is unavailable in {workspace_type} workspace"
    return await tr.acall(name, arguments)


def call_workspace_tool(
    workspace_type: str,
    name: str,
    arguments: dict,
) -> object:
    """Synchronous compatibility entrypoint used by existing tests/callers."""

    if workspace_type != "learning" and name in _LEARNING_ONLY_TOOLS:
        return f"[Error]: tool {name!r} is unavailable in {workspace_type} workspace"
    return tr.call(name, arguments)


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


def build_user_profile_context(
    user: UserRecord,
) -> str | None:
    """[已废弃] 旧扁平学情档案构建函数，保留签名用于向后兼容。"""
    return None


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

    def _prepare_run(
        self,
        input: str,
        user_name: str,
        history: list[dict] | None,
        prompt_ctx: PromptContext | None = None,
        total_weeks: int | None = None,
    ) -> tuple[list[dict], list[dict]]:
        prompt_ctx = prompt_ctx or PromptContext()
        history = sanitize_qwen_history(history or [])

        set_current_user(user_name)
        set_current_conversation_mode(prompt_ctx.conversation_mode)

        if total_weeks is not None:
            set_current_total_weeks(total_weeks)

        # 轻量确定性路由选中策略后按需加载 Skill 正文，
        # 主 Agent 仍需结合用户当前消息决定具体执行。
        if prompt_ctx.workspace_type == "learning":
            decision = PedagogyRouter.route(
                input,
                history=history,
                profile=prompt_ctx.user_profile_context,
            )
            loaded_skill_body = (
                load_skill(decision.skill_name)
                if decision.skill_name is not None
                else None
            )
            prompt_ctx = replace(
                prompt_ctx,
                pedagogy_context=decision.to_prompt_context(
                    loaded_skill_body=loaded_skill_body,
                ),
                autoload_skills_context=build_autoload_skills_context(),
            )
        else:
            prompt_ctx = replace(
                prompt_ctx,
                pedagogy_context="",
                autoload_skills_context="",
            )
        skills_context = build_skills_context(
            categories=None
            if prompt_ctx.workspace_type == "learning"
            else {"attachment"}
        )

        system_prompt = build_system_prompt(
            user_name=user_name,
            skills_context=skills_context,
            prompt_ctx=prompt_ctx,
        )

        user_message = {
            "role": "user",
            "content": input,
        }

        messages = [
            {
                "role": "system",
                "content": system_prompt,
            },
            *history,
            user_message,
        ]

        new_messages = [
            {
                **user_message,
                "is_visible": True,
            }
        ]

        return messages, new_messages

    async def run(
        self,
        input: str,
        user_name: str,
        history: list[dict] | None = None,
        prompt_ctx: PromptContext | None = None,
        total_weeks: int | None = None,
    ) -> list[dict]:
        """
        运行一轮非流式对话。

        返回本轮新消息（用户输入 + 助手回复 + Tool 结果），调用方可直接持久化。
        """
        workspace_type = (prompt_ctx or PromptContext()).workspace_type
        tool_schemas = tool_schemas_for_workspace(workspace_type)
        messages, new_messages = self._prepare_run(
            input,
            user_name,
            history,
            prompt_ctx=prompt_ctx,
            total_weeks=total_weeks,
        )
        attachment_context = (prompt_ctx or PromptContext()).attachment_tool_context
        tool_scope = (
            attachment_tool_context(attachment_context)
            if isinstance(attachment_context, AttachmentToolContext)
            else nullcontext()
        )

        with tool_scope:
            return await self._run_loop(
                messages,
                new_messages,
                workspace_type,
                tool_schemas,
            )

    async def _run_loop(
        self,
        messages: list[dict],
        new_messages: list[dict],
        workspace_type: str,
        tool_schemas: list[dict],
    ) -> list[dict]:
        for _ in range(self.loop_times):
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
                result = await call_workspace_tool_async(
                    workspace_type,
                    tool_call.name,
                    tool_call.arguments,
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
        input: str,
        user_name: str,
        history: list[dict] | None = None,
        prompt_ctx: PromptContext | None = None,
        total_weeks: int | None = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        workspace_type = (prompt_ctx or PromptContext()).workspace_type
        tool_schemas = tool_schemas_for_workspace(workspace_type)
        messages, new_messages = self._prepare_run(
            input,
            user_name,
            history,
            prompt_ctx=prompt_ctx,
            total_weeks=total_weeks,
        )
        attachment_context = (prompt_ctx or PromptContext()).attachment_tool_context
        tool_scope = (
            attachment_tool_context(attachment_context)
            if isinstance(attachment_context, AttachmentToolContext)
            else nullcontext()
        )

        with tool_scope:
            async for event in self._run_stream_loop(
                messages,
                new_messages,
                workspace_type,
                tool_schemas,
            ):
                yield event

    async def _run_stream_loop(
        self,
        messages: list[dict],
        new_messages: list[dict],
        workspace_type: str,
        tool_schemas: list[dict],
    ) -> AsyncIterator[AgentStreamEvent]:
        for _ in range(self.loop_times):
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
                    call_workspace_tool_async(
                        workspace_type,
                        tool_call.name,
                        tool_call.arguments,
                    )
                )
                while True:
                    try:
                        result = await asyncio.wait_for(
                            asyncio.shield(tool_task),
                            timeout=15,
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
