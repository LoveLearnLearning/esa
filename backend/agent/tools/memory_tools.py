# backend/agent/tools/memory_tools.py

from contextvars import ContextVar
from typing import Any

from backend.agent.memories.core_memory import CoreMemory
from backend.agent.tools import ROOT_DIR
from backend.agent.tools.tools import tr

current_user: ContextVar[str | None] = ContextVar(
    "current_user",
    default=None,
)

core_memory = CoreMemory(
    database_path=ROOT_DIR.parent / "memories" / "data" / "core_memory.db",
)


def set_current_user(user_name: str) -> None:
    """辅助函数：设置当前用户名
    Args:
        user_name: str => 用户名

    Returns:
        None => 函数无返回值 通过修改 current_user 实现异步和协程
    """
    user_name = user_name.strip()

    if not user_name:
        raise ValueError("用户名不能为空！")

    current_user.set(user_name)


def get_current_user() -> str:
    """辅助函数：获取当前用户名

    Returns:
        str => 用户名
    """

    user_name = current_user.get()

    if user_name is None:
        raise RuntimeError("当前未设置用户名！")

    return user_name


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "save_core_memory",
            "description": (
                "保存用户长期稳定的信息"
                "例如用户偏好  学习目标  项目信息"
                "只有当用户明确要求记住或信息长期有效时才调用"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_key": {
                        "type": "string",
                        "description": (
                            "记忆的唯一名称",
                            "例如：response_style 或者是 learning goal",
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "需要长期保存的记忆内容",
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "profile",
                            "preference",
                            "learning",
                            "project",
                            "constraint",
                            "general",
                        ],
                        "description": "记忆的分类",
                        "default": "general",
                    },
                },
                "required": [
                    "memory_key",
                    "content",
                ],
            },
        },
    }
)
def save_core_memory(
    memory_key: str,
    content: str,
    category: str = "general",
) -> dict[str, Any]:
    user_name = get_current_user()

    saved = core_memory.set(
        user_name=user_name,
        memory_key=memory_key,
        content=content,
        category=category,
    )

    return {
        "saved": saved,
        "memory_key": memory_key,
        "content": content,
        "category": category,
    }


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "get_core_memories",
            "description": "查看该用户所有已保存的核心记忆",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
)
def get_core_memories() -> dict[str, Any]:
    user_name = get_current_user()

    memories = core_memory.get_all(user_name)

    return {
        "count": len(memories),
        "memories": memories,
    }


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "delete_core_memory",
            "description": (
                "删除当前用户的一条核心记忆"
                "只有当用户明确要忘掉某一个记忆的时候才能调用"
                "不允许自行调用"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_key": {
                        "type": "string",
                        "description": "需要删除的记忆的名称",
                    },
                },
                "required": [
                    "memory_key",
                ],
            },
        },
    }
)
def delete_core_memory(memory_key: str) -> dict[str, Any]:
    user_name = get_current_user()

    deleted = core_memory.delete(
        user_name=user_name,
        memory_key=memory_key,
    )

    return {
        "deleted": deleted,
        "memory_key": memory_key,
    }
