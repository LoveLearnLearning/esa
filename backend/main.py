# backend/main.py

from backend.agent.agent import Agent

# from backend.core.agent.tools.tools import tr
from backend.core.log.logger import setup_logging

# from backend.core.service.vllm_service import LLM_Provider
# from backend.core.utils.parser import parse_output

MODEL_PATH = "Qwen/Qwen3.5-9B"

setup_logging()


def main() -> None:

    # messages = [{"role": "user", "content": "北京天气怎么样, 并给我计算2 和 3的和"}]

    # llm_provider = LLM_Provider(
    #     MODEL_PATH,
    #     gpu_memory_utilization=0.85,
    #     max_model_len=4096,
    # )

    # llm_provider.load_model()
    # prompt = llm_provider.build_prompt(messages, tr.schemas)
    # print(parse_output(llm_provider.generate([prompt])))
    # llm_provider.unload_model()
    agent = Agent(MODEL_PATH)

    agent.run("北京天气怎么样, 并给我计算2 和 3的和")


if __name__ == "__main__":
    main()
