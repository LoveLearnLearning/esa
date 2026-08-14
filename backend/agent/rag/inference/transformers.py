# backend/agent/rag/inference/transformers.py

"""

这个文件干什么：直接使用 Transformers 执行 Qwen3 Embedding 与 Reranker 推理。

直白点说就是：直接用 Transformers 加载 Qwen3 模型，计算文本向量和相关性分数。

直接使用 Transformers 执行 Qwen3 Embedding 与 Reranker 推理。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..fingerprints import configuration_sha256
from .errors import InferenceUnavailable


@dataclass
class TransformersEmbeddingProvider:
    """延迟加载的 Transformers Qwen3 Embedding 后端。"""

    model_name: str = "Qwen/Qwen3-Embedding-4B"
    load_path: str | None = None
    device: str = "cuda"
    # ``device`` is part of the frozen embedding fingerprint.  Cluster
    # launchers may expose the same CUDA device under another logical index;
    # keep that placement detail out of the semantic index identity.
    runtime_device: str | None = None
    dimension: int = 2560
    max_length: int = 8192
    batch_size: int = 8
    query_instruction: str = (
        "Given a web search query, retrieve relevant passages that answer the query"
    )
    _tokenizer: Any = field(init=False, default=None, repr=False)
    _model: Any = field(init=False, default=None, repr=False)
    _torch: Any = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        if self.dimension <= 0:
            raise ValueError("dimension must be positive")
        if self.max_length <= 0:
            raise ValueError("max_length must be positive")
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")

    @property
    def configuration_fingerprint(self) -> str:
        """记录影响文档向量内容的本地推理配置。"""

        return configuration_sha256(
            {
                "backend": "transformers-qwen3-embedding-0.1",
                "model_name": self.model_name,
                "device": self.device,
                "dimension": self.dimension,
                "max_length": self.max_length,
                "batch_size": self.batch_size,
                "query_instruction": self.query_instruction,
                "torch_dtype": "auto",
                "pooling": "last-token-l2-normalized",
            }
        )

    def _load(self) -> None:
        """首次推理时加载 tokenizer、模型和 torch。"""

        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except ImportError as exc:
            raise InferenceUnavailable(
                "Transformers embedding dependencies are not installed"
            ) from exc
        self._torch = torch
        source = self.load_path or self.model_name
        self._tokenizer = AutoTokenizer.from_pretrained(
            source,
            padding_side="left",
        )
        target_device = self.runtime_device or self.device
        self._model = (
            AutoModel.from_pretrained(source, torch_dtype="auto")
            .to(target_device)
            .eval()
        )

    def warmup(self) -> None:
        """Load model weights during application startup."""

        self._load()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """按固定批大小执行编码，避免整库 Padding 和显存峰值。"""

        if not texts:
            return []
        self._load()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed_batch(texts[start : start + self.batch_size]))
        return vectors

    def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """执行单批最后有效 Token 池化和 L2 归一化。"""

        encoded = self._tokenizer(
            list(texts),
            padding=True,
            truncation=True,
            max_length=self.max_length,
            return_tensors="pt",
        )
        target_device = self.runtime_device or self.device
        encoded = {name: value.to(target_device) for name, value in encoded.items()}
        with self._torch.inference_mode():
            hidden = self._model(**encoded).last_hidden_state
            pooled = self._torch.nn.functional.normalize(hidden[:, -1], p=2, dim=1)
        return pooled.float().cpu().tolist()

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """不添加查询指令，编码文档文本。"""

        return self.embed(texts)

    def embed_query(self, query: str) -> list[float]:
        """添加查询指令并编码单个问题。"""

        prompt = f"Instruct: {self.query_instruction}\nQuery: {query}"
        return self.embed([prompt])[0]

    def count_tokens(self, text: str) -> int:
        """使用实际 Qwen tokenizer 计算 Context 预算。"""

        self._load()
        return len(self._tokenizer.encode(text, add_special_tokens=False))


@dataclass
class TransformersReranker:
    """按 Qwen3 官方 yes/no token 概率执行重排。"""

    model_name: str = "Qwen/Qwen3-Reranker-4B"
    load_path: str | None = None
    device: str = "cuda"
    max_length: int = 8192
    instruction: str = (
        "Given a web search query, retrieve relevant passages that answer the query"
    )
    _tokenizer: Any = field(init=False, default=None, repr=False)
    _model: Any = field(init=False, default=None, repr=False)
    _torch: Any = field(init=False, default=None, repr=False)
    _false_id: int = field(init=False, default=0, repr=False)
    _true_id: int = field(init=False, default=0, repr=False)
    _prefix_tokens: list[int] = field(init=False, default_factory=list, repr=False)
    _suffix_tokens: list[int] = field(init=False, default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.max_length <= 0:
            raise ValueError("max_length must be positive")

    @property
    def configuration_fingerprint(self) -> str:
        """记录影响重排分数的本地推理配置。"""

        return configuration_sha256(
            {
                "backend": "transformers-qwen3-reranker-0.1",
                "model_name": self.model_name,
                "device": self.device,
                "max_length": self.max_length,
                "instruction": self.instruction,
                "torch_dtype": "auto",
                "score": "yes-no-probability",
            }
        )

    def _load(self) -> None:
        """首次推理时加载生成式模型及固定提示 Token。"""

        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise InferenceUnavailable(
                "Transformers reranker dependencies are not installed"
            ) from exc
        self._torch = torch
        source = self.load_path or self.model_name
        self._tokenizer = AutoTokenizer.from_pretrained(
            source,
            padding_side="left",
        )
        self._model = (
            AutoModelForCausalLM.from_pretrained(
                source,
                torch_dtype="auto",
            )
            .to(self.device)
            .eval()
        )
        self._false_id = self._tokenizer.convert_tokens_to_ids("no")
        self._true_id = self._tokenizer.convert_tokens_to_ids("yes")
        prefix = (
            "<|im_start|>system\n"
            "Judge whether the Document meets the requirements based on "
            "the Query and the Instruct provided. Note that the answer can "
            'only be "yes" or "no".'
            "<|im_end|>\n<|im_start|>user\n"
        )
        suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        self._prefix_tokens = self._tokenizer.encode(
            prefix,
            add_special_tokens=False,
        )
        self._suffix_tokens = self._tokenizer.encode(
            suffix,
            add_special_tokens=False,
        )

    def warmup(self) -> None:
        """Load model weights during application startup."""

        self._load()

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        """为每个候选计算归一化的 yes 概率。"""

        if not documents:
            return []
        self._load()
        texts = [
            (
                f"<Instruct>: {self.instruction}\n"
                f"<Query>: {query}\n"
                f"<Document>: {document}"
            )
            for document in documents
        ]
        pairs = self._tokenizer(
            texts,
            padding=False,
            truncation=True,
            max_length=(
                self.max_length - len(self._prefix_tokens) - len(self._suffix_tokens)
            ),
        )
        pairs["input_ids"] = [
            self._prefix_tokens + value + self._suffix_tokens
            for value in pairs["input_ids"]
        ]
        pairs = self._tokenizer.pad(
            pairs,
            padding=True,
            return_tensors="pt",
            max_length=self.max_length,
        )
        pairs = {name: value.to(self.device) for name, value in pairs.items()}
        with self._torch.inference_mode():
            logits = self._model(**pairs).logits[:, -1, :]
            binary = self._torch.stack(
                [logits[:, self._false_id], logits[:, self._true_id]],
                dim=1,
            )
            scores = self._torch.nn.functional.log_softmax(binary, dim=1)[:, 1].exp()
        return scores.float().cpu().tolist()
