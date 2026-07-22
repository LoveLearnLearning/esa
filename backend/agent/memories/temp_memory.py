# backend/agent/memories/temp_memory.py

from dataclasses import dataclass, field


@dataclass
class TempMemory:
    max_messages_per_user: int = 20
    messages: list[dict[str, str]] = field(default_factory=list)

    def __trim(self, user_name: str) -> None:
        user_message_indexes = [
            index
            for index, message in enumerate(self.messages)
            if message["user_name"] == user_name
        ]

        overflow = len(user_message_indexes) - self.max_messages_per_user

        if overflow <= 0:
            return

        indexes_to_remove = set(user_message_indexes[:overflow])

        self.messages = [
            message
            for index, message in enumerate(self.messages)
            if index not in indexes_to_remove
        ]

    def add(
        self,
        role: str,
        content: str,
        user_name: str,
    ) -> None:
        content = content.strip()

        if not content:
            return

        self.messages.append(
            {
                "role": role,
                "content": content,
                "user_name": user_name,
            }
        )

        self.__trim(user_name)

    def get_messages(
        self,
        user_name: str,
    ) -> list[dict[str, str]]:
        return [
            message.copy()
            for message in self.messages
            if message["user_name"] == user_name
        ]

    def build_context(self, user_name: str) -> str:
        messages = self.get_messages(user_name)

        if not messages:
            return "暂无用户记忆"

        role_names = {
            "user": "用户",
            "assistant": "助手",
            "tool": "工具",
        }

        return "\n".join(
            f"{role_names.get(message['role'], message['role'])}  {message['content']}"
            for message in messages
        )

    def clear(self, user_name: str | None = None) -> None:
        if user_name is None:
            self.messages.clear()
            return

        self.messages = [
            message for message in self.messages if message["user_name"] != user_name
        ]
