# backend/main.py

from backend.core.log.logger import setup_logging
from backend.core.service.vllm_service import LLM_Provider

MODEL_PATH = "Qwen/Qwen3.5-9B"

setup_logging()


def main() -> None:
    tools = [
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
    ]

    messages = [{"role": "user", "content": "北京天气怎么样"}]

    llm_provider = LLM_Provider(
        MODEL_PATH,
        gpu_memory_utilization=0.85,
        max_model_len=4096,
    )

    llm_provider.load_model()
    prompt = llm_provider.build_prompt(messages, tools)
    print(llm_provider.generate([prompt]))
    llm_provider.unload_model()


if __name__ == "__main__":
    main()
