# backend/main.py

from backend.core.agent.tools.tool_register import ToolRegistry
from backend.core.log.logger import setup_logging
from backend.core.service.vllm_service import LLM_Provider
from backend.core.utils.parser import parse_output

MODEL_PATH = "Qwen/Qwen3.5-9B"

setup_logging()

tr = ToolRegistry()


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取城市天气",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                    }
                },
                "required": ["city"],
            },
        },
    }
)
def get_weather():
    raise NotImplementedError


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "add_two_nums",
            "description": "求两数之和",
            "parameters": {
                "type": "object",
                "properties": {
                    "num1": {
                        "type": "float",
                    },
                    "num2": {
                        "type": "float",
                    },
                },
                "required": ["num1", "num2"],
            },
        },
    }
)
def add_two_num():
    raise NotImplementedError


def main() -> None:

    messages = [{"role": "user", "content": "北京天气怎么样, 并给我计算2 和 3的和"}]

    llm_provider = LLM_Provider(
        MODEL_PATH,
        gpu_memory_utilization=0.85,
        max_model_len=4096,
    )

    llm_provider.load_model()
    prompt = llm_provider.build_prompt(messages, tr.schemas)
    print(parse_output(llm_provider.generate([prompt])))
    llm_provider.unload_model()


if __name__ == "__main__":
    main()
