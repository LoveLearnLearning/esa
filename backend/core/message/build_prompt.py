# backend/core/message/build_prompt.py

SYSTEM_PROMPT: str = """
# 你是一个帮助学生学习的 Agent

你会有很多可用的 tools 供你调用
"""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT
