# backend/core/services/vllm_service.py

"""提供领域服务实现。"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

from transformers import AutoTokenizer
from vllm import SamplingParams
from vllm.config.cache import CacheDType
from vllm.config.model import ModelDType
from vllm.engine.arg_utils import AsyncEngineArgs
from vllm.lora.request import LoRARequest
from vllm.model_executor.layers.quantization import QuantizationMethods
from vllm.sampling_params import RequestOutputKind
from vllm.v1.engine.async_llm import AsyncLLM

from backend.core.utils.config import LOG_PROMPTS
from backend.core.utils.models import ParsedOutput
from backend.core.utils.parser import StreamOutputParser, parse_output

logger = logging.getLogger(__name__)


def _log_model_prompt(
    request_id: str,
    conversation_id: str | None,
    prompt: str,
) -> None:
    """记录发送给主模型的最终 chat-template prompt。"""

    if not LOG_PROMPTS:
        return
    logger.info(
        "LLM prompt start model=main request_id=%s chars=%d",
        request_id,
        len(prompt),
    )
    logger.info(
        "LLM prompt body model=main request_id=%s conversation_id=%s\n%s",
        request_id,
        conversation_id or "-",
        prompt,
    )
    logger.info(
        "LLM prompt end model=main request_id=%s conversation_id=%s",
        request_id,
        conversation_id or "-",
    )


class LLMProvider:
    """封装 `LLMProvider` 的状态与行为。"""
    def __init__(
        self,
        model_path: str | Path,
        gpu_memory_utilization: float = 0.95,
        max_model_len: int = 32768,
        max_output_tokens: int = 8192,
        quantization: QuantizationMethods | None = None,
        dtype: ModelDType = "auto",
        kv_cache_dtype: CacheDType = "auto",
        max_num_seqs: int = 1,
        tensor_parallel_size: int = 1,
        lora_path: str | Path | None = None,
        lora_name: str = "esa-agent",
        lora_max_rank: int = 16,
        enforce_eager: bool = False,
        performance_mode: Literal[
            "balanced", "interactivity", "throughput"
        ] = "interactivity",
        fully_sharded_loras: bool = False,
        specialize_active_lora: bool = True,
    ) -> None:
        """初始化 `LLMProvider` 实例。"""
        self.model_path = Path(model_path)
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens 必须大于 0")
        if lora_max_rank <= 0:
            raise ValueError("lora_max_rank 必须大于 0")
        self.max_output_tokens = max_output_tokens
        self.lora_request: LoRARequest | None = None
        if lora_path is not None:
            resolved_lora_path = Path(lora_path).expanduser().resolve()
            if not resolved_lora_path.is_dir():
                raise FileNotFoundError(f"LoRA 目录不存在：{resolved_lora_path}")
            if not (resolved_lora_path / "adapter_config.json").is_file():
                raise FileNotFoundError(
                    f"LoRA 配置不存在：{resolved_lora_path / 'adapter_config.json'}"
                )
            if not (resolved_lora_path / "adapter_model.safetensors").is_file():
                raise FileNotFoundError(
                    "LoRA 权重不存在："
                    f"{resolved_lora_path / 'adapter_model.safetensors'}"
                )
            if not lora_name.strip():
                raise ValueError("lora_name 不能为空")
            self.lora_request = LoRARequest(
                lora_name=lora_name,
                lora_int_id=1,
                lora_path=str(resolved_lora_path),
                base_model_name=str(self.model_path),
            )
        logger.info(
            "正在加载千问模型：path=%s，LoRA=%s，TP=%s，"
            "max_model_len=%s，max_output_tokens=%s，enforce_eager=%s，"
            "performance_mode=%s，fully_sharded_loras=%s，"
            "specialize_active_lora=%s",
            self.model_path,
            self.lora_request.lora_path if self.lora_request else "disabled",
            tensor_parallel_size,
            max_model_len,
            max_output_tokens,
            enforce_eager,
            performance_mode,
            fully_sharded_loras,
            specialize_active_lora,
        )

        engine_args = AsyncEngineArgs(
            model=str(self.model_path),
            gpu_memory_utilization=gpu_memory_utilization,
            max_model_len=max_model_len,
            max_num_seqs=max_num_seqs,
            tensor_parallel_size=tensor_parallel_size,
            enforce_eager=enforce_eager,
            quantization=quantization,
            dtype=dtype,
            kv_cache_dtype=kv_cache_dtype,
            enable_lora=self.lora_request is not None,
            max_loras=1,
            max_lora_rank=lora_max_rank,
            fully_sharded_loras=fully_sharded_loras,
            specialize_active_lora=specialize_active_lora,
            performance_mode=performance_mode,
        )

        self.engine = AsyncLLM.from_engine_args(engine_args)
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_path))
        logger.info("模型加载完成：path=%s", self.model_path)

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
        return self.tokenizer.apply_chat_template(
            messages,
            tools=tools,
            tokenize=False,
            add_generation_prompt=True,
        )

    def count_tokens(self, text: str) -> int:
        """Count serialized observation tokens with the actual Agent tokenizer."""

        return len(self.tokenizer.encode(text, add_special_tokens=False))

    def parse_output(
        self,
        raw_text: str,
        tools: list[dict] | tuple[dict, ...] | None = None,
    ) -> ParsedOutput:
        """解析千问 XML 协议的完整输出。"""
        return parse_output(raw_text, tool_schemas=tools)

    def create_stream_parser(self) -> StreamOutputParser:
        """创建千问 XML 协议的流式解析器。"""
        return StreamOutputParser()

    async def generate(
        self,
        prompts: list[dict],
        tools: list[dict],
        request_id: str | None = None,
        conversation_id: str | None = None,
    ) -> str:
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

        async for chunk in self.generate_stream(
            prompts,
            tools,
            request_id=request_id,
            conversation_id=conversation_id,
        ):
            chunks.append(chunk)

        return "".join(chunks)

    async def generate_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        request_id: str | None = None,
        conversation_id: str | None = None,
    ) -> AsyncIterator[str]:
        """生成 `stream` 相关数据。

        Args:
            messages: list[dict] => 消息列表。
            tools: list[dict] => 可用工具列表。
            request_id: str | None => request ID。

        Returns:
            AsyncIterator[str] => 处理结果。
        """
        request_id = request_id or str(uuid.uuid4())

        prompt = self.build_prompt(messages, tools)
        _log_model_prompt(request_id, conversation_id, prompt)

        sampling_params = SamplingParams(
            temperature=0.7,
            top_p=0.8,
            max_tokens=self.max_output_tokens,
            output_kind=RequestOutputKind.DELTA,
        )

        async for output in self.engine.generate(
            request_id=request_id,
            prompt=prompt,
            sampling_params=sampling_params,
            lora_request=self.lora_request,
        ):
            for completion in output.outputs:
                if completion.text:
                    yield completion.text

            if output.finished:
                break
