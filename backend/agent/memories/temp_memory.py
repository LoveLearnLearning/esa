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
        user_name: str | None = None,
    ) -> None:
        message = {
            "role": role,
            "content": content,
        }

        if user_name is not None:
            message["user_name"] = user_name

        self.messages.append(message)
        self.__trim()

    def build_context(self, user_name: str | None = None) -> str:
        messages = self.messages
        if user_name is not None:
            messages = [
                message for message in messages if message.get("user_name") == user_name
            ]

        if not messages:
            return "暂无用户记忆"

        lines: list[str] = []

        for message in messages:
            role = message["role"]
            content = message["content"]

            if role == "user":
                role_name = "用户"
            elif role == "assistant":
                role_name = "助手"
            elif role == "tool":
                role_name = "工具"
            else:
                role_name = role

            lines.append(f"{role_name}  {content}")

        return "\n".join(lines)
