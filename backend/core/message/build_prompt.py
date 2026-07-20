# backend/core/message/build_prompt.py

SYSTEM_PROMPT: str = """
# 你是一个帮助学生学习的 Agent

你会有很多可用的 tools 供你调用

# 记忆使用规则

你可以参考下面提供的用户记忆来回答问题
只使用与当前问题相关的记忆
记忆与用户最新要求冲突时  以用户最新要求为准
不要主动向用户暴露内部记忆结构
不要编造记忆中不存在的信息
"""


def build_system_prompt(memory: str | None = None) -> str:
    memory_content = memory.strip() if memory else "暂无用户记忆"

    return f"""
{SYSTEM_PROMPT.strip()}

# 用户记忆

{memory_content}
""".strip()
