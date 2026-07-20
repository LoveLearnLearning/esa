# backend/agent/memories/temp_memory.py

from dataclasses import dataclass, field


@dataclass
class TempMemory:
    max_messages: int = 20
    messages: list[dict] = field(default_factory=list)

    def get_messages(self) -> list[dict]:
        return self.messages.copy()

    def clear(self) -> None:
        self.messages.clear()

    def __trim(self) -> None:
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]

    def add(
        self,
        role: str,
        content: str,
        name: str | None = None,
    ) -> None:
        message = {
            "role": role,
            "content": content,
        }

        if name is not None:
            message["name"] = name

        self.messages.append(message)
        self.__trim()
