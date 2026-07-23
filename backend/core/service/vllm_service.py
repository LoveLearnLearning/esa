# backend/core/service/vllm_service.py

import logging
from pathlib import Path

import torch
from transformers import AutoTokenizer
from vllm import LLM, SamplingParams

logger = logging.getLogger(__name__)


class LLM_Provider:
    def __init__(
        self,
        model_path: str | Path,
        gpu_memory_utilization: float = 0.85,
        max_model_len: int = 4096,
    ) -> None:
        self.model_path = Path(model_path)
        self.gpu_memory_utilization = gpu_memory_utilization
        self.max_model_len = max_model_len

        self.llm = None

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
        """构造 vllm 支持的输入提示词

        Args:
            messages: list[dict]    => 输入的提示词 dict 格式如下:
                {
                    "role": "消息的角色",
                    "content": "消息的内容,
                },

            tools: list             => 包含 tools 的列表

        Returns:
            str                     => 构造好的 prompt
        """
        assert self.tokenizer is not None
        return self.tokenizer.apply_chat_template(
            messages,
            tools=tools,
            tokenize=False,
            add_generation_prompt=True,
        )

    def generate(self, prompts: list, tools: list) -> str:
        """生成 LLM 的返回信息
        Args:
            prompts: list           => 输入的提示词 dict 格式如下:
                {
                    "role": "消息的角色",
                    "content": "消息的内容,
                },

            tools: list             => 包含 tools 的列表

        Returns:
            LLM 模型返回的信息
        """
        assert self.llm is not None
        outputs = self.llm.chat(
            messages=prompts,
            sampling_params=self.sampling_params,
            tools=tools,
            add_generation_prompt=True,
        )
        return outputs[0].outputs[0].text
