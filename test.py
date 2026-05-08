import os

from dotenv import load_dotenv

from core.llm_service import LLM
from core.prompt import Prompt

load_dotenv()


def main():
    prompt = Prompt(user_name="张三")
    llm = LLM(
        api_key=str(os.environ.get("DEEPSEEK_API_KEY")),
        model="deepseek-v4-flash",
        reasoning_effort="low",
        thinking=True,
    )

    while True:
        input_message = input("User: \n")
        if input_message.lower() == "exit":
            del prompt
            break

        message = prompt.build_messages(user_input=input_message)
        result = llm.chat(message)
        prompt.update_history(response=result)
        print(f"AI: \n{result}")


if __name__ == "__main__":
    main()
