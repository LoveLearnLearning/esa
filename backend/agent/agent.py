# backend/agent/agent.py

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from vllm.config.cache import CacheDType
from vllm.config.model import ModelDType
from vllm.model_executor.layers.quantization import QuantizationMethods

from backend.agent.memories.temp_memory import TempMemory
from backend.agent.tools import tr
from backend.agent.tools.mastery_tools import (
    kg_store,
    mastery_store,
    set_current_total_weeks,
)
from backend.agent.tools.memory_tools import core_memory, set_current_user
from backend.agent.tools.skills import build_skills_context, load_skill
from backend.core.message.build_prompt import build_system_prompt
from backend.core.services.vllm_service import LLMProvider
from backend.core.utils.config import DEBUG_MODE
from backend.core.utils.models import (
    AgentStreamEvent,
    ParsedOutput,
    PromptContext,
    ToolCall,
    UserRecord,
)

ROOT_PATH: Path = Path.cwd().parent


def build_user_profile_context(
    user: UserRecord,
) -> str | None:
    """构建用户学情档案文本

    检查 user.profile_enabled：
      - False 时返回 None，Agent 不注入学情档案
      - True 时返回含掌握度概况 + 教学进度 + profile_personalization skill 内容的文本

    Args:
        user: UserRecord => 当前用户数据对象（含 profile_enabled/current_week/total_weeks）

    Returns:
        str | None => 学情档案文本（非空时由 _prepare_run 注入 build_system_prompt）
    """
    if not user.profile_enabled:
        return None

    # 获取全局掌握度报告
    report = mastery_store.get_report(
        user_name=user.username,
        kg_store=kg_store,
    )

    parts: list[str] = []

    # 掌握度概况
    if report["total_points"] > 0:
        parts.append(f"掌握度概况: 平均掌握度 {report['avg_mastery']:.0f}")

        if report["weak_points"]:
            wp = "  ".join(
                f"{p['name']}({p['mastery_level']:.0f})"
                for p in report["weak_points"][:3]
            )
            parts.append(f"薄弱知识点: {wp}")

        if report["strong_points"]:
            sp = "  ".join(
                f"{p['name']}({p['mastery_level']:.0f})"
                for p in report["strong_points"][:3]
            )
            parts.append(f"掌握较好知识点: {sp}")
    else:
        parts.append("暂无掌握度数据  开始练习后可生成学情档案")

    # 教学进度
    parts.append(f"教学进度: 第 {user.current_week} 周 / 共 {user.total_weeks} 周")

    # 加载 profile_personalization skill 内容（学科身份/讲解深度/来源标注/AI 标识规则）
    skill_body = load_skill("profile_personalization")
    if skill_body and "skill not found" not in skill_body:
        parts.append(skill_body)

    return "\n\n".join(parts)


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
        max_num_seqs: int = 1,
        tensor_parallel_size: int = 1,
        model_adapter: str = "auto",
    ) -> None:
        self.loop_times = loop_times
        self.llm_provider = LLMProvider(
            model_path=model_path,
            quantization=quantization,
            dtype=dtype,
            kv_cache_dtype=kv_cache_dtype,
            gpu_memory_utilization=gpu_memory_utilization,
            max_model_len=max_model_len,
            max_num_seqs=max_num_seqs,
            tensor_parallel_size=tensor_parallel_size,
            model_adapter=model_adapter,
        )
        self.temp_memory = TempMemory(
            max_messages_per_user=20,
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
        set_current_user(user_name)

        if total_weeks is not None:
            set_current_total_weeks(total_weeks)

        temp_context = (
            "历史消息已由 messages 提供"
            if history
            else self.temp_memory.build_context(user_name)
        )
        core_context = core_memory.build_context(user_name)
        skills_context = build_skills_context()

        system_prompt = build_system_prompt(
            user_name=user_name,
            temp_memory=temp_context,
            core_memory=core_context,
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
            *(history or []),
            user_message,
        ]

        new_messages = [
            {
                **user_message,
                "is_visible": True,
            }
        ]

        self.temp_memory.add(
            role="user",
            content=input,
            user_name=user_name,
        )

        return messages, new_messages

    async def run(
        self,
        input: str,
        user_name: str,
        history: list[dict] | None = None,
        prompt_ctx: PromptContext | None = None,
        total_weeks: int | None = None,
    ) -> list[dict]:
        """运行一轮对话
        Args:
            input: str                        => 用户输入
            user_name: str                    => 用户名
            history: list[dict] | None = None => 历史消息 每条包含 role content
                                                 tool 消息可以额外带 name 字段
                                                 由 ChatStore.get_model_messages() 提供
            prompt_ctx: PromptContext | None = None => prompt 构建上下文 含风格/语调/指令/学情档案/分组级参数
            total_weeks: int | None           => 学期总周数 用于 set_current_total_weeks

        Returns:
            list[dict] => 本轮新产生的消息 (用户输入 + 助手回复 + 工具结果)
                          调用方可直接交给 ChatStore.append_messages() 持久化
        """

        messages, new_messages = self._prepare_run(
            input,
            user_name,
            history,
            prompt_ctx=prompt_ctx,
            total_weeks=total_weeks,
        )

        for _ in range(self.loop_times):
            response = await self.llm_provider.generate(
                messages,
                tr.schemas,
            )

            po: ParsedOutput = self.llm_provider.parse_output(response)
            tcs: list[ToolCall] = po.tool_calls

            if DEBUG_MODE:
                print(f"Thinking: {po.reasoning}")
                print(f"Agent: {po.content}")

            if not tcs:
                assistant_content = po.content or response.strip()

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

                self.temp_memory.add(
                    role="assistant",
                    content=assistant_content,
                    user_name=user_name,
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

            for tc in tcs:
                result = await asyncio.to_thread(
                    tr.call,
                    tc.name,
                    tc.arguments,
                )

                result_text = str(result)

                messages.append(
                    {
                        "role": "tool",
                        "name": tc.name,
                        "content": result_text,
                    }
                )

                new_messages.append(
                    {
                        "role": "tool",
                        "name": tc.name,
                        "content": result_text,
                        "is_visible": True,
                    }
                )

                self.temp_memory.add(
                    role="tool",
                    content=f"name: {tc.name}, content: {result_text}",
                    user_name=user_name,
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
        messages, new_messages = self._prepare_run(
            input,
            user_name,
            history,
            prompt_ctx=prompt_ctx,
            total_weeks=total_weeks,
        )

        for _ in range(self.loop_times):
            stream_parser = self.llm_provider.create_stream_parser()

            async for chunk in self.llm_provider.generate_stream(
                messages,
                tr.schemas,
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
            parsed = self.llm_provider.parse_output(response)

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

                self.temp_memory.add(
                    role="assistant",
                    content=assistant_content,
                    user_name=user_name,
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
                result = await asyncio.to_thread(
                    tr.call,
                    tool_call.name,
                    tool_call.arguments,
                )

                result_text = str(result)

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
                        "name": tool_call.name,
                        "content": result_text,
                    },
                )

                self.temp_memory.add(
                    role="tool",
                    content=f"name: {tool_call.name}, content: {result_text}",
                    user_name=user_name,
                )
        yield AgentStreamEvent(
            event="complete",
            data={"messages": new_messages},
        )
