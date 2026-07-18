# backend/core/agent/agent.py

from pathlib import Path

from backend.agent.tools import tr
from backend.core.message.build_prompt import build_system_prompt
from backend.core.service.vllm_service import LLM_Provider
from backend.core.utils.models import ParsedOutput, ToolCall
from backend.core.utils.parser import parse_output


class Agent:
    def __init__(
        self,
        model_path: str | Path,
        loop_times: int = 3,
    ) -> None:
        self.loop_times = loop_times
        self.llm_provider = LLM_Provider(model_path)

    def run(self, input: str) -> None:
        if not self.llm_provider.llm:
            self.llm_provider.load_model()

        system_prompt = build_system_prompt()
        messages: list = [{"role": "system", "content": system_prompt}]
        messages.append({"role": "user", "content": input})
        for _ in range(self.loop_times):
            response = self.llm_provider.generate(messages, tr.schemas)
            po: ParsedOutput = parse_output(response)
            messages.append({"role": "assistant", "content": response})
            tcs: list[ToolCall] = po.tool_calls
            print(po)
            if not tcs:
                break
            for tc in tcs:
                result = tr.call(tc.name, tc.arguments)
                messages.append(
                    {"role": "tool", "name": tc.name, "content": str(result)}
                )
