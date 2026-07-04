from transformers import AutoTokenizer
from vllm import LLM

MODEL_PATH: str = "~/models/Qwen3.5-9B"


def main() -> None:
    llm = LLM(
        model=MODEL_PATH,
        tensor_parallel_size=1,
        max_model_len=32768,
        gpu_memory_utilization=0.85,
    )

    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)


if __name__ == "__main__":
    main()
