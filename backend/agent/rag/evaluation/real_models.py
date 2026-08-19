# backend/agent/rag/evaluation/real_models.py

"""

这个文件干什么：在单张 GPU 上分别压测真实 Qwen3 Embedding 与 Reranker。

直白点说就是：分别启动真实 Embedding 和 Reranker 做压测，避免两个大模型同时挤爆一张显卡。

在单张 GPU 上分别压测真实 Qwen3 Embedding 与 Reranker。

压测只读取正式 ChunkCollection；两个后端必须由两个独立进程串行运行，避免
模型同时驻留显存。JSON 结果使用稳定键顺序写入，便于后续机器比较。
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import platform
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ..paths import WORKSPACE_ROOT

DEFAULT_COLLECTION = (
    WORKSPACE_ROOT
    / "artifacts/chunk/collections/collection_bc7a6054e159eb7346e94df0"
)
DEFAULT_OUTPUT = WORKSPACE_ROOT / "artifacts/rag/benchmarks/real-models-20260803"
MODELS = {
    "embedding": "Qwen/Qwen3-Embedding-4B",
    "reranker": "Qwen/Qwen3-Reranker-4B",
}
QUERY_INSTRUCTION = (
    "Given a web search query, retrieve relevant passages that answer the query"
)
RERANK_PREFIX = (
    "<|im_start|>system\n"
    "Judge whether the Document meets the requirements based on the Query and "
    'the Instruct provided. Note that the answer can only be "yes" or "no".'
    "<|im_end|>\n<|im_start|>user\n"
)
RERANK_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


def _sha256(path: Path) -> str:
    """处理 `_sha256` 相关逻辑。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_collection_texts(root: Path) -> tuple[dict[str, Any], list[str]]:
    """加载并校验 manifest 中引用的 Chunk 文档，返回真实 dense_text。"""

    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    texts: list[str] = []
    for entry in manifest["documents"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe collection path: {relative}")
        path = root / relative
        if _sha256(path) != entry["sha256"]:
            raise ValueError(f"chunk document hash mismatch: {relative}")
        document = json.loads(path.read_text(encoding="utf-8"))
        texts.extend(chunk["dense_text"] for chunk in document["chunks"])
    if len(texts) != manifest["chunk_count"]:
        raise ValueError("manifest chunk count does not match loaded texts")
    if not texts or any(not text.strip() for text in texts):
        raise ValueError("collection contains empty benchmark text")
    return manifest, texts


def _gpu_snapshot() -> dict[str, Any]:
    """处理 `_gpu_snapshot` 相关逻辑。"""
    command = [
        "nvidia-smi",
        "--query-gpu=name,driver_version,memory.total,memory.used,memory.free",
        "--format=csv,noheader,nounits",
    ]
    value = subprocess.check_output(command, text=True).strip().split(", ")
    return {
        "name": value[0],
        "driver_version": value[1],
        "memory_total_mib": int(value[2]),
        "memory_used_mib": int(value[3]),
        "memory_free_mib": int(value[4]),
    }


def _model_revision(model_path: str) -> str | None:
    """处理 `_model_revision` 相关逻辑。"""
    revision_file = Path(model_path) / "REVISION"
    if revision_file.is_file():
        return revision_file.read_text(encoding="utf-8").strip() or None
    parts = Path(model_path).parts
    if "snapshots" in parts:
        index = parts.index("snapshots")
        if index + 1 < len(parts):
            return parts[index + 1]
    return None


def _error_record(exc: BaseException) -> dict[str, Any]:
    """处理 `_error_record` 相关逻辑。"""
    message = " ".join(str(exc).split())
    return {"status": "oom" if "out of memory" in message.lower() else "error", "error": message[:1000]}


def _cuda_mib(torch: Any, value: int) -> float:
    """处理 `_cuda_mib` 相关逻辑。"""
    return round(value / (1024 * 1024), 2)


def _measure(
    torch: Any,
    prepare: Callable[[], tuple[dict[str, Any], int]],
    infer: Callable[[dict[str, Any]], Any],
    batch_size: int,
    repeats: int,
) -> dict[str, Any]:
    """分别计时 CPU 分词/传输、GPU 推理和端到端延迟。"""

    try:
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        warm_inputs, _ = prepare()
        with torch.inference_mode():
            _ = infer(warm_inputs)
        torch.cuda.synchronize()
        del warm_inputs, _
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

        prepare_ms: list[float] = []
        infer_ms: list[float] = []
        total_ms: list[float] = []
        token_counts: list[int] = []
        last_output = None
        for _index in range(repeats):
            total_start = time.perf_counter()
            prepare_start = total_start
            inputs, tokens = prepare()
            torch.cuda.synchronize()
            infer_start = time.perf_counter()
            with torch.inference_mode():
                last_output = infer(inputs)
            torch.cuda.synchronize()
            end = time.perf_counter()
            prepare_ms.append((infer_start - prepare_start) * 1000)
            infer_ms.append((end - infer_start) * 1000)
            total_ms.append((end - total_start) * 1000)
            token_counts.append(tokens)
            del inputs

        mean_total = sum(total_ms) / len(total_ms)
        mean_infer = sum(infer_ms) / len(infer_ms)
        mean_tokens = sum(token_counts) / len(token_counts)
        result = {
            "status": "ok",
            "batch_size": batch_size,
            "sequence_tokens": token_counts[-1] // batch_size,
            "total_tokens": token_counts[-1],
            "prepare_ms_mean": round(sum(prepare_ms) / len(prepare_ms), 3),
            "gpu_infer_ms_mean": round(mean_infer, 3),
            "end_to_end_ms_mean": round(mean_total, 3),
            "end_to_end_ms_min": round(min(total_ms), 3),
            "end_to_end_ms_max": round(max(total_ms), 3),
            "items_per_second": round(batch_size * 1000 / mean_total, 3),
            "tokens_per_second_gpu": round(mean_tokens * 1000 / mean_infer, 3),
            "peak_allocated_mib": _cuda_mib(torch, torch.cuda.max_memory_allocated()),
            "peak_reserved_mib": _cuda_mib(torch, torch.cuda.max_memory_reserved()),
        }
        if last_output is not None:
            result["output_shape"] = list(last_output.shape)
        return result
    except (RuntimeError, torch.cuda.OutOfMemoryError) as exc:
        result = _error_record(exc)
        result["batch_size"] = batch_size
        result["peak_allocated_mib"] = _cuda_mib(torch, torch.cuda.max_memory_allocated())
        result["peak_reserved_mib"] = _cuda_mib(torch, torch.cuda.max_memory_reserved())
        gc.collect()
        torch.cuda.empty_cache()
        return result


def _make_token_text(tokenizer: Any, target_tokens: int) -> str:
    """处理 `_make_token_text` 相关逻辑。"""
    seed = "这是用于真实模型显存与上下文长度压测的中文技术文本，包含表格、公式与检索证据。"
    text = seed
    while len(tokenizer.encode(text, add_special_tokens=False)) < target_tokens:
        text += seed
    ids = tokenizer.encode(text, add_special_tokens=False)[:target_tokens]
    return tokenizer.decode(ids, skip_special_tokens=True)


def _base_result(
    backend: str,
    model_name: str,
    model_path: str,
    manifest: dict[str, Any],
    texts: Sequence[str],
    torch: Any,
) -> dict[str, Any]:
    """处理 `_base_result` 相关逻辑。"""
    return {
        "schema_name": "rag-real-model-benchmark",
        "schema_version": "1.0",
        "backend": backend,
        "model_name": model_name,
        "model_path": model_path,
        "model_revision": _model_revision(model_path),
        "dtype": "bfloat16",
        "attention_implementation": "sdpa",
        "collection_id": manifest["collection_id"],
        "collection_chunk_count": len(texts),
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "gpu_before_load": _gpu_snapshot(),
        },
    }


def benchmark_embedding(
    model_name: str,
    model_path: str,
    manifest: dict[str, Any],
    texts: Sequence[str],
    repeats: int,
) -> dict[str, Any]:
    """处理 `benchmark_embedding` 相关逻辑。

    Args:
        model_name: str => `model_name` 参数。
        model_path: str => `model_path` 参数。
        manifest: dict[str, Any] => `manifest` 参数。
        texts: Sequence[str] => `texts` 参数。
        repeats: int => `repeats` 参数。

    Returns:
        dict[str, Any] => 处理结果。
    """
    import torch
    from transformers import AutoModel, AutoTokenizer

    result = _base_result("embedding", model_name, model_path, manifest, texts, torch)
    load_start = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(model_path, padding_side="left", local_files_only=True)
    model = AutoModel.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        attn_implementation="sdpa",
        local_files_only=True,
    ).to("cuda").eval()
    torch.cuda.synchronize()
    result["load_seconds"] = round(time.perf_counter() - load_start, 3)
    result["model_allocated_mib"] = _cuda_mib(torch, torch.cuda.memory_allocated())
    result["gpu_after_load"] = _gpu_snapshot()
    result["embedding_dimension"] = int(model.config.hidden_size)

    def run(raw_texts: Sequence[str], max_length: int) -> tuple[Callable[[], tuple[dict[str, Any], int]], Callable[[dict[str, Any]], Any]]:
        """执行 `run` 相关数据。

        Args:
            raw_texts: Sequence[str] => `raw_texts` 参数。
            max_length: int => `max_length` 参数。

        Returns:
            tuple[Callable[[], tuple[dict[str, Any], int]], Callable[[dict[str, Any]], Any]] => 处理结果。
        """
        def prepare() -> tuple[dict[str, Any], int]:
            """准备 `prepare` 相关数据。"""
            encoded = tokenizer(
                list(raw_texts), padding=True, truncation=True, max_length=max_length,
                return_tensors="pt",
            )
            tokens = int(encoded["attention_mask"].sum().item())
            return ({key: value.to("cuda") for key, value in encoded.items()}, tokens)

        def infer(inputs: dict[str, Any]) -> Any:
            """处理 `infer` 相关逻辑。"""
            hidden = model(**inputs).last_hidden_state
            return torch.nn.functional.normalize(hidden[:, -1], p=2, dim=1)

        return prepare, infer

    ordered = sorted(texts, key=lambda value: len(tokenizer.encode(value, add_special_tokens=False)))
    sample = [ordered[round(index * (len(ordered) - 1) / 63)] for index in range(64)]
    real_runs = []
    for batch in (1, 2, 4, 8, 16):
        prepare, infer = run(sample[:batch], 1024)
        item = _measure(torch, prepare, infer, batch, repeats)
        item["workload"] = "real_collection"
        real_runs.append(item)
    result["real_collection_runs"] = real_runs

    length_runs = []
    for length in (128, 512, 1024, 2048, 4096):
        synthetic = _make_token_text(tokenizer, length)
        prepare, infer = run([synthetic], length)
        item = _measure(torch, prepare, infer, 1, repeats)
        item["workload"] = "length_sweep"
        item["requested_tokens"] = length
        length_runs.append(item)
    result["length_sweep_runs"] = length_runs

    query = f"Instruct: {QUERY_INSTRUCTION}\nQuery: 什么是检索增强生成中的证据链？"
    relevant = "检索增强生成会保存文档、分块、元素和页码之间的证据映射，以便回答可追溯。"
    irrelevant = "今天天气晴朗，适合户外运动。"
    prepare, infer = run([query, relevant, irrelevant], 512)
    inputs, _ = prepare()
    with torch.inference_mode():
        vectors = infer(inputs).float().cpu()
    similarities = torch.matmul(vectors[0], vectors[1:].T).tolist()
    norms = torch.linalg.vector_norm(vectors, dim=1).tolist()
    result["correctness"] = {
        "query_relevant_cosine": round(float(similarities[0]), 6),
        "query_irrelevant_cosine": round(float(similarities[1]), 6),
        "relevant_ranked_first": bool(similarities[0] > similarities[1]),
        "vector_norms": [round(float(value), 6) for value in norms],
    }
    result["gpu_after_benchmark"] = _gpu_snapshot()
    return result


def benchmark_reranker(
    model_name: str,
    model_path: str,
    manifest: dict[str, Any],
    texts: Sequence[str],
    repeats: int,
) -> dict[str, Any]:
    """处理 `benchmark_reranker` 相关逻辑。

    Args:
        model_name: str => `model_name` 参数。
        model_path: str => `model_path` 参数。
        manifest: dict[str, Any] => `manifest` 参数。
        texts: Sequence[str] => `texts` 参数。
        repeats: int => `repeats` 参数。

    Returns:
        dict[str, Any] => 处理结果。
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    result = _base_result("reranker", model_name, model_path, manifest, texts, torch)
    load_start = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(model_path, padding_side="left", local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        attn_implementation="sdpa",
        local_files_only=True,
    ).to("cuda").eval()
    torch.cuda.synchronize()
    result["load_seconds"] = round(time.perf_counter() - load_start, 3)
    result["model_allocated_mib"] = _cuda_mib(torch, torch.cuda.memory_allocated())
    result["gpu_after_load"] = _gpu_snapshot()
    false_id = tokenizer.convert_tokens_to_ids("no")
    true_id = tokenizer.convert_tokens_to_ids("yes")
    prefix_ids = tokenizer.encode(RERANK_PREFIX, add_special_tokens=False)
    suffix_ids = tokenizer.encode(RERANK_SUFFIX, add_special_tokens=False)
    domain_query = "DocIR 如何保留 PDF 表格和证据定位？"

    def run(
        documents: Sequence[str],
        max_length: int,
        query: str = domain_query,
    ) -> tuple[Callable[[], tuple[dict[str, Any], int]], Callable[[dict[str, Any]], Any]]:
        """执行 `run` 相关数据。

        Args:
            documents: Sequence[str] => `documents` 参数。
            max_length: int => `max_length` 参数。
            query: str => 查询文本。

        Returns:
            tuple[Callable[[], tuple[dict[str, Any], int]], Callable[[dict[str, Any]], Any]] => 处理结果。
        """
        payloads = [
            f"<Instruct>: {QUERY_INSTRUCTION}\n<Query>: {query}\n<Document>: {document}"
            for document in documents
        ]

        def prepare() -> tuple[dict[str, Any], int]:
            """准备 `prepare` 相关数据。"""
            body_limit = max_length - len(prefix_ids) - len(suffix_ids)
            pairs = tokenizer(payloads, padding=False, truncation=True, max_length=body_limit)
            pairs["input_ids"] = [prefix_ids + ids + suffix_ids for ids in pairs["input_ids"]]
            padded = tokenizer.pad(pairs, padding=True, return_tensors="pt", max_length=max_length)
            tokens = int(padded["attention_mask"].sum().item())
            return ({key: value.to("cuda") for key, value in padded.items()}, tokens)

        def infer(inputs: dict[str, Any]) -> Any:
            """处理 `infer` 相关逻辑。"""
            logits = model(**inputs).logits[:, -1, :]
            binary = torch.stack([logits[:, false_id], logits[:, true_id]], dim=1)
            return torch.nn.functional.log_softmax(binary, dim=1)[:, 1].exp()

        return prepare, infer

    def score(query: str, documents: Sequence[str]) -> list[float]:
        """复用相同推理路径计算一组正确性哨兵分数。"""

        prepare, infer = run(documents, 512, query)
        inputs, _ = prepare()
        with torch.inference_mode():
            return infer(inputs).float().cpu().tolist()

    ordered = sorted(texts, key=lambda value: len(tokenizer.encode(value, add_special_tokens=False)))
    sample = [ordered[round(index * (len(ordered) - 1) / 31)] for index in range(32)]
    real_runs = []
    for batch in (1, 2, 4, 8):
        prepare, infer = run(sample[:batch], 1024)
        item = _measure(torch, prepare, infer, batch, repeats)
        item["workload"] = "real_collection"
        real_runs.append(item)
    result["real_collection_runs"] = real_runs

    length_runs = []
    overhead = len(prefix_ids) + len(suffix_ids) + 64
    for length in (128, 512, 1024, 2048):
        document = _make_token_text(tokenizer, max(16, length - overhead))
        prepare, infer = run([document], length)
        item = _measure(torch, prepare, infer, 1, repeats)
        item["workload"] = "length_sweep"
        item["requested_tokens"] = length
        length_runs.append(item)
    result["length_sweep_runs"] = length_runs

    official_scores = score(
        "What is the capital of China?",
        [
            "The capital of China is Beijing.",
            "Gravity attracts bodies and governs planetary motion.",
        ],
    )
    domain_scores = score(
        domain_query,
        [
            "DocIR 的表格元素保存 HTML，Evidence 记录 Locator、文本层和 span，可回查原始文档。",
            "今天天气晴朗，适合户外运动。",
        ],
    )
    result["correctness"] = {
        "official_relevant_score": round(float(official_scores[0]), 6),
        "official_irrelevant_score": round(float(official_scores[1]), 6),
        "official_relevant_ranked_first": bool(official_scores[0] > official_scores[1]),
        "domain_relevant_score": round(float(domain_scores[0]), 6),
        "domain_irrelevant_score": round(float(domain_scores[1]), 6),
        "domain_relevant_ranked_first": bool(domain_scores[0] > domain_scores[1]),
        "scores_in_probability_range": all(
            0.0 <= value <= 1.0 for value in official_scores + domain_scores
        ),
        "yes_token_id": int(true_id),
        "no_token_id": int(false_id),
    }
    result["gpu_after_benchmark"] = _gpu_snapshot()
    return result


def _write_json(path: Path, value: dict[str, Any]) -> None:
    """写入 `json` 相关数据。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    """运行当前模块的命令行入口。

    Args:
        argv: Sequence[str] | None => `argv` 参数。

    Returns:
        int => 处理结果。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", choices=sorted(MODELS))
    parser.add_argument("--collection", type=Path, default=DEFAULT_COLLECTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    manifest, texts = load_collection_texts(args.collection)
    function = benchmark_embedding if args.backend == "embedding" else benchmark_reranker
    result = function(MODELS[args.backend], args.model_path, manifest, texts, args.repeats)
    result["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    result["result_sha256_scope"] = "all fields except this field"
    output = args.output / f"{args.backend}.json"
    _write_json(output, result)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
