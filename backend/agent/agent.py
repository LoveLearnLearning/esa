# backend/core/agent/agent.py

from pathlib import Path

from backend.agent.memories.temp_memory import TempMemory
from backend.agent.tools import tr
from backend.agent.tools.memory_tools import core_memory, set_current_user
from backend.agent.tools.skills import build_skills_context
from backend.core.message.build_prompt import build_system_prompt
from backend.core.service.vllm_service import LLM_Provider
from backend.core.utils.models import ParsedOutput, ToolCall
from backend.core.utils.parser import parse_output

ROOT_PATH: Path = Path.cwd().parent


class Agent:
    def __init__(
        self,
        model_path: str | Path,
        loop_times: int = 3,
    ) -> None:
        self.loop_times = loop_times
        self.llm_provider = LLM_Provider(model_path)
        self.temp_memory = TempMemory(
            max_messages_per_user=20,
        )

    def start(self) -> bool:
        """启动 Agent 加载模型"""
        if not self.llm_provider.llm:
            self.llm_provider.load_model()
            if not self.llm_provider.llm:
                return False
        return True

    def run(self, input: str, user_name: str) -> None:

        set_current_user(user_name)

        temp_context: str = self.temp_memory.build_context(user_name)
        core_context: str = core_memory.build_context(user_name)
        skills_context: str = build_skills_context()

        system_prompt: str = build_system_prompt(
            temp_memory=temp_context,
            core_memory=core_context,
            skills_context=skills_context,
        )

        messages: list = [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": input,
            },
        ]
        self.temp_memory.add(
            role="user",
            content=input,
            user_name=user_name,
        )
        for _ in range(self.loop_times):
            response = self.llm_provider.generate(
                messages,
                tr.schemas,
            )

            po: ParsedOutput = parse_output(response)

            messages.append(
                {
                    "role": "assistant",
                    "content": response,
                }
            )

            tcs: list[ToolCall] = po.tool_calls
            if not tcs:
                if po.content:
                    self.temp_memory.add(
                        role="assistant",
                        content=po.content,
                        user_name=user_name,
                    )
                break
            for tc in tcs:
                result = tr.call(
                    tc.name,
                    tc.arguments,
                )
                messages.append(
                    {
                        "role": "tool",
                        "name": tc.name,
                        "content": str(result),
                    }
                )
                self.temp_memory.add(
                    "tool",
                    f"name: {tc.name}, content: {(str(result))}",
                    user_name,
                )
