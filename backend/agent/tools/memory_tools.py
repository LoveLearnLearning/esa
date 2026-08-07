# backend/agent/tools/memory_tools.py

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import Any

from backend.agent.memories.core_memory import CoreMemory
from backend.agent.tools.tools import tr

current_user: ContextVar[str | None] = ContextVar(
    "current_user",
    default=None,
)

# 当前会话记忆模式: normal(读取并写入) / no_write(只读不写) / isolated(不读不写)
# 由 Agent._prepare_run 注入；所有长期状态工具都必须遵守这里的读写边界。
current_conversation_mode: ContextVar[str] = ContextVar(
    "current_conversation_mode",
    default="normal",
)

MEMORIES_DIR = Path(__file__).resolve().parent.parent / "memories"

core_memory = CoreMemory(
    database_path=MEMORIES_DIR / "data" / "core_memory.db",
)


def set_current_user(user_name: str) -> None:
    """设置当前用户名。"""
    user_name = user_name.strip()
    if not user_name:
        raise ValueError("用户名不能为空！")
    current_user.set(user_name)


def set_current_conversation_mode(mode: str) -> None:
    """设置当前会话记忆模式: normal / no_write / isolated。"""
    if mode not in {"normal", "no_write", "isolated"}:
        raise ValueError(f"不支持的 conversation_mode={mode!r}")
    current_conversation_mode.set(mode)


def get_current_conversation_mode() -> str:
    """获取当前会话记忆模式。"""
    return current_conversation_mode.get()


def memory_read_allowed() -> bool:
    """
    当前会话是否允许读取长期状态。

    normal/no_write 可读；isolated 必须完全隔离，不允许通过 Tool 绕过
    system prompt 主动读取 CoreMemory、Mastery、LearningEvidence 等状态。
    """
    return current_conversation_mode.get() != "isolated"


def memory_write_allowed() -> bool:
    """
    当前会话是否允许写入长期状态。

    仅 normal 允许写；no_write / isolated 禁止新增、更新和删除长期状态。
    """
    return current_conversation_mode.get() == "normal"


def get_current_user() -> str:
    """获取当前用户名。"""
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
                "例如用户偏好 学习目标 项目信息；"
                "只有当用户明确要求记住或信息长期有效时才调用"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_key": {
                        "type": "string",
                        "description": (
                            "记忆的唯一名称 例如 response_style 或 learning_goal"
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

    if not memory_write_allowed():
        return {
            "saved": False,
            "memory_key": memory_key,
            "content": content,
            "category": category,
            "reason": "当前会话为 no_write/isolated 模式，禁止写入记忆",
        }

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
            "name": "search_core_memories",
            "description": (
                "按需检索与当前任务相关的少量长期核心记忆。"
                "仅当当前问题确实依赖过去的偏好、目标、项目、约束或已记住事实时调用；"
                "不要在每轮对话开始时例行调用。isolated 会话不可读取"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要检索的具体主题，例如 Python 偏好、当前项目、学习目标",
                    },
                    "category": {
                        "type": "string",
                        "description": "可选记忆类别过滤；不确定时留空",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "description": "最多返回多少条，默认 5",
                    },
                },
                "required": ["query"],
            },
        },
    }
)
def search_core_memories(
    query: str,
    category: str = "",
    limit: int = 5,
) -> dict[str, Any]:
    user_name = get_current_user()

    if not memory_read_allowed():
        return {
            "allowed": False,
            "query": query,
            "count": 0,
            "memories": [],
            "reason": "当前会话为 isolated 模式，禁止读取长期记忆",
        }

    memories = core_memory.search(
        user_name=user_name,
        query=query,
        category=category.strip() or None,
        limit=limit,
    )
    compact = [
        {
            "memory_key": item["memory_key"],
            "content": item["content"],
            "category": item["category"],
            "updated_at": item["updated_at"],
        }
        for item in memories
    ]
    return {
        "allowed": True,
        "query": query,
        "count": len(compact),
        "memories": compact,
    }


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "get_core_memories",
            "description": (
                "列出当前用户全部核心记忆。仅当用户明确要求查看、管理或核对"
                "系统记住了什么时调用；一般任务应优先使用 search_core_memories。"
                "isolated 会话不可读取"
            ),
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

    if not memory_read_allowed():
        return {
            "allowed": False,
            "count": 0,
            "memories": [],
            "reason": "当前会话为 isolated 模式，禁止读取长期记忆",
        }

    memories = core_memory.get_all(user_name)

    return {
        "allowed": True,
        "count": len(memories),
        "memories": memories,
    }


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "delete_core_memory",
            "description": (
                "删除当前用户的一条核心记忆；"
                "只有当用户明确要求忘掉某条记忆时才能调用，"
                "no_write/isolated 会话不可删除"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_key": {
                        "type": "string",
                        "description": "需要删除的记忆名称",
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

    if not memory_write_allowed():
        return {
            "deleted": False,
            "memory_key": memory_key,
            "reason": "当前会话为 no_write/isolated 模式，禁止删除长期记忆",
        }

    deleted = core_memory.delete(
        user_name=user_name,
        memory_key=memory_key,
    )

    return {
        "deleted": deleted,
        "memory_key": memory_key,
    }
