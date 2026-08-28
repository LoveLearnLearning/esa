"""Measure real Qwen first-call prompts on a configured Slurm node.

Example (host and paths are supplied by the operator; nothing is hard-coded):

    srun -p <partition> --gres=gpu:1 python backend/scripts/evaluate_prompt_budget.py \
      --partition <partition> --model-path <model> --project-dir <esa-root>
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path


def _nearest_rank(values: list[int], percentile: float) -> int:
    if not values:
        raise ValueError("no prompt samples were measured")
    return sorted(values)[math.ceil(len(values) * percentile) - 1]


def _first_call(record: dict) -> tuple[list[dict], list[dict]]:
    system = str(record.get("system") or "")
    messages = [{"role": "system", "content": system}]
    for turn in record.get("conversations", []):
        if turn.get("from") == "human":
            messages.append({"role": "user", "content": str(turn.get("value", ""))})
            break
    raw_tools = record.get("tools") or "[]"
    tools = json.loads(raw_tools) if isinstance(raw_tools, str) else raw_tools
    return messages, tools


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure actual Qwen template tokens without running generation."
    )
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--partition", required=True)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument(
        "--dataset",
        default="backend/scripts/dataset/data/out/esa_agent_train.jsonl",
    )
    parser.add_argument("--output")
    parser.add_argument("--max-samples", type=int, default=0)
    args = parser.parse_args()

    project_dir = Path(args.project_dir).expanduser().resolve()
    dataset = Path(args.dataset)
    if not dataset.is_absolute():
        dataset = project_dir / dataset
    if not project_dir.is_dir():
        raise SystemExit(f"project directory does not exist: {project_dir}")
    if not dataset.is_file():
        raise SystemExit(f"dataset does not exist: {dataset}")

    from transformers import AutoTokenizer  # imported only on the evaluation node

    tokenizer = AutoTokenizer.from_pretrained(
        args.model_path,
        trust_remote_code=True,
    )
    prompt_tokens: list[int] = []
    tool_tokens: list[int] = []
    with dataset.open(encoding="utf-8") as stream:
        for line in stream:
            if args.max_samples and len(prompt_tokens) >= args.max_samples:
                break
            record = json.loads(line)
            messages, tools = _first_call(record)
            tokenized = tokenizer.apply_chat_template(
                messages,
                tools=tools,
                tokenize=True,
                add_generation_prompt=True,
            )
            input_ids = (
                tokenized["input_ids"]
                if isinstance(tokenized, dict)
                else tokenized
            )
            prompt_tokens.append(len(input_ids))
            tool_text = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
            tool_tokens.append(
                len(tokenizer.encode(tool_text, add_special_tokens=False))
            )

    report = {
        "model_path": args.model_path,
        "project_dir": str(project_dir),
        "requested_partition": args.partition,
        "slurm_partition": os.environ.get("SLURM_JOB_PARTITION"),
        "dataset": str(dataset),
        "samples": len(prompt_tokens),
        "prompt_tokens": {
            "p50": _nearest_rank(prompt_tokens, 0.50),
            "p95": _nearest_rank(prompt_tokens, 0.95),
            "max": max(prompt_tokens),
        },
        "tool_tokens": {
            "p95": _nearest_rank(tool_tokens, 0.95),
            "max": max(tool_tokens),
        },
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
