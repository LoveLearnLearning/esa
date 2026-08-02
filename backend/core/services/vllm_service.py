# backend/core/services/vllm_service.py

import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from transformers import AutoTokenizer
from vllm import SamplingParams
from vllm.config.cache import CacheDType
from vllm.config.model import ModelDType
from vllm.engine.arg_utils import AsyncEngineArgs
from vllm.model_executor.layers.quantization import QuantizationMethods
from vllm.sampling_params import RequestOutputKind
from vllm.v1.engine.async_llm import AsyncLLM

logger = logging.getLogger(__name__)


class LLMProvider:
    def __init__(
        self,
        model_path: str | Path,
        gpu_memory_utilization: float = 0.95,
        max_model_len: int = 32768,
        quantization: QuantizationMethods | None = None,
        dtype: ModelDType = "auto",
        kv_cache_dtype: CacheDType = "auto",
        max_num_seqs: int = 1,
        tensor_parallel_size: int = 1,
    ) -> None:
        self.model_path = Path(model_path)

        engine_args = AsyncEngineArgs(
            model=str(self.model_path),
            gpu_memory_utilization=gpu_memory_utilization,
            max_model_len=max_model_len,
            max_num_seqs=max_num_seqs,
            tensor_parallel_size=tensor_parallel_size,
            enforce_eager=True,
            quantization=quantization,
            dtype=dtype,
            kv_cache_dtype=kv_cache_dtype,
        )

        self.engine = AsyncLLM.from_engine_args(engine_args)
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_path))

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

    async def generate(self, prompts: list[dict], tools: list[dict]) -> str:
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
        chunks: list[str] = []

        async for chunk in self.generate_stream(prompts, tools):
            chunks.append(chunk)

        return "".join(chunks)

    async def generate_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        request_id: str | None = None,
    ) -> AsyncIterator[str]:
        request_id = request_id or str(uuid.uuid4())

        prompt = self.build_prompt(messages, tools)

        sampling_params = SamplingParams(
            temperature=0.7,
            top_p=0.8,
            max_tokens=2048,
            output_kind=RequestOutputKind.DELTA,
        )

        async for output in self.engine.generate(
            request_id=request_id,
            prompt=prompt,
            sampling_params=sampling_params,
        ):
            for completion in output.outputs:
                if completion.text:
                    yield completion.text

            if output.finished:
                break
