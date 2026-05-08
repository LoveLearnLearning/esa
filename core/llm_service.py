# core/llm_service.py

from typing import Literal

from openai import OpenAI


class LLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        thinking: bool,
        reasoning_effort: Literal["high", "low", "medium"],
        base_url: str = "https://api.deepseek.com",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.reasoning_effort: Literal["high", "low", "medium"] = reasoning_effort
        self.base_url = base_url
        self.thinking = thinking
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    def chat(self, messages: list) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=False,
                reasoning_effort=self.reasoning_effort,
                extra_body={
                    "thinking": {"type": "enabled" if self.thinking else "disabled"}
                },
            )
            return str(response.choices[0].message.content)

        except Exception as e:
            raise RuntimeError(f"Chat request failed: {e}")
