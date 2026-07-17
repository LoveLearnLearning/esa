# backend/core/service/vllm_service.py

from transformers import AutoTokenizer
from vllm import LLM, SamplingParams

MODEL_PATH = "Qwen/Qwen3.5-9B"


class LLM_Provider:
    def __init__(self) -> None:
        # 加载模型
        llm = LLM(
            model=MODEL_PATH,
            tensor_parallel_size=1,
            max_model_len=4096,
            enforce_eager=True,
            gpu_memory_utilization=0.85,
        )

        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)

        sampling_params = SamplingParams(
            temperature=0.7,
            top_p=0.8,
            max_tokens=2048,
        )

        messages = [{"role": "user", "content": "北京天气怎么样"}]

    def build_prompt(self, messages: list[dict], tools: list) -> str:
        return self.tokenizer.apply_chat_template(
            messages,
            tools=tools,
            tokenize=False,
            add_generation_prompt=True,
        )


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

    print(prompt)

    outputs = llm.generate([prompt], sampling_params)
    raw_text = outputs[0].outputs[0].text
    print(raw_text)


if __name__ == "__main__":
    main()
