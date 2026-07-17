# backend/core/service/vllm_service.py

import logging
from pathlib import Path

import torch
from transformers import AutoTokenizer
from vllm import LLM, SamplingParams

from backend.core.log.logger import setup_logging

MODEL_PATH = "Qwen/Qwen3.5-9B"


setup_logging()
logger = logging.getLogger(__name__)


class LLM_Provider:
    def __init__(
        self,
        model_path: str | Path,
        gpu_memory_utilization: float,
        max_model_len: int,
    ) -> None:
        self.model_path = Path(model_path)
        self.gpu_memory_utilization = gpu_memory_utilization
        self.max_model_len = max_model_len

        # 加载模型
        self.llm = LLM(
            model=MODEL_PATH,
            tensor_parallel_size=1,
            max_model_len=4096,
            enforce_eager=True,
            gpu_memory_utilization=0.85,
        )

    def load_model(self) -> None:
        """
        加载模型
        """
        if self.llm is None:
            logger.info(f"正在加载模型：{self.model_path}")

            self.llm = LLM(
                model=str(self.model_path),
                gpu_memory_utilization=self.gpu_memory_utilization,
                max_model_len=self.max_model_len,
                tensor_parallel_size=1,
                enforce_eager=True,
            )

            # 加载分词器
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)

            # 模型参数设置：选词方式
            self.sampling_params = SamplingParams(
                temperature=0.7,
                top_p=0.8,
                max_tokens=2048,
            )
            logger.info(f"模型{self.model_path.name}加载完成")
        else:
            logger.info(f"模型{self.model_path.name}已加载")

    def unload_model(self) -> None:
        """
        卸载模型
        """
        if self.llm is not None:
            logger.info(f"正在卸载模型{self.model_path.name}")
            del self.llm
            self.llm = None

            if self.tokenizer:
                del self.tokenizer
                self.tokenizer = None

            torch.cuda.empty_cache()
            logger.info(f"模型{self.model_path.name}已关闭")
        else:
            logger.info(f"模型{self.model_path.name}并未加载")

    def build_prompt(self, messages: list[dict], tools: list) -> str:
        assert self.tokenizer is not None
        return self.tokenizer.apply_chat_template(
            messages,
            tools=tools,
            tokenize=False,
            add_generation_prompt=True,
        )

    def generate(self, prompt: list) -> str:
        assert self.llm is not None
        outputs = self.llm.generate(prompt, self.sampling_params)
        return outputs[0].outputs[0].text


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

    prompt = llm_provider.build_prompt(messages, tools)
    print(llm_provider.generate([prompt]))


if __name__ == "__main__":
    main()
