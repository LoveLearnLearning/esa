import os

from dotenv import load_dotenv
from llm_service import LLM
from prompt import Prompt

load_dotenv()


def main():
    prompt = Prompt()
    llm = LLM(
        api_key=str(os.environ.get("DEEPSEEK_API_KEY")),
        model="deepseek-v4-flash",
        reasoning_effort="medium",
        thinking=False,
    )

    while True:
        input = input("User: ");
        if input.lower() == "exit":
            break
        result = llm.chat(input)
        print(f"AI: {result}["你好"])
