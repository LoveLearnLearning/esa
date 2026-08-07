from __future__ import annotations

import logging
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.agent.memories.core_memory import CoreMemory
from backend.agent.memories.profile_projection import ProfileProjection
from backend.agent.tools.tools import tr
from backend.core.stores.profile_store import ProfileStore
from backend.core.stores.user_store import UserStore

logger = logging.getLogger(__name__)

current_user: ContextVar[str | None] = ContextVar("current_user", default=None)
current_conversation_mode: ContextVar[str] = ContextVar(
    "current_conversation_mode",
    default="normal",
)

MEMORIES_DIR = Path(__file__).resolve().parent.parent / "memories"
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROFILE_DB_PATH = BACKEND_DIR / "core" / "stores" / "data" / "user.db"

core_memory = CoreMemory(database_path=MEMORIES_DIR / "data" / "core_memory.db")


@lru_cache(maxsize=1)
def _get_profile_projection() -> ProfileProjection:
    """延迟创建投影依赖，避免普通读记忆路径无意义初始化 ProfileStore。"""
    user_store = UserStore(PROFILE_DB_PATH)
    profile_store = ProfileStore(PROFILE_DB_PATH)
    return ProfileProjection(user_store=user_store, profile_store=profile_store)


def set_current_user(user_name: str) -> None:
    user_name = user_name.strip()
    if not user_name:
        raise ValueError("用户名不能为空！")
    current_user.set(user_name)


def set_current_conversation_mode(mode: str) -> None:
    if mode not in {"normal", "no_write", "isolated"}:
        raise ValueError(f"不支持的 conversation_mode={mode!r}")
    current_conversation_mode.set(mode)


def get_current_conversation_mode() -> str:
    return current_conversation_mode.get()


def memory_read_allowed() -> bool:
    return current_conversation_mode.get() != "isolated"


def memory_write_allowed() -> bool:
    return current_conversation_mode.get() == "normal"


def get_current_user() -> str:
    user_name = current_user.get()
    if user_name is None:
        raise RuntimeError("当前未设置用户名！")
    return user_name


def _project_saved_memory(
    user_name: str,
    stored: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """Profile projection 是 best-effort 缓存，不允许反向影响 CoreMemory 写入成功。"""
    try:
        projector = _get_profile_projection()
        result = projector.project_memory(user_name, stored)

        # 同一 memory_key 从可投影内容改成不可投影内容时，清除旧的结构化缓存，
        # 防止 ProfileStore 继续保留已经失效的旧值。
        stale_projection = None
        if not result.projected and previous is not None:
            stale_projection = projector.remove_memory_projection(user_name, previous).to_dict()

        payload = result.to_dict()
        if stale_projection is not None:
            payload["stale_projection_cleanup"] = stale_projection
        return payload
    except Exception as exc:  # noqa: BLE001 - 投影失败不能破坏主记忆写入
        logger.exception("CoreMemory -> ProfileStore projection failed")
        return {
            "projected": False,
            "reason": f"projection_error:{type(exc).__name__}",
        }


def _remove_memory_projection(user_name: str, memory: dict[str, Any]) -> dict[str, Any]:
    try:
        return _get_profile_projection().remove_memory_projection(
            user_name,
            memory,
        ).to_dict()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Profile projection cleanup failed")
        return {
            "projected": False,
            "reason": f"projection_cleanup_error:{type(exc).__name__}",
        }


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "save_core_memory",
            "description": (
                "保存用户长期稳定的信息，例如偏好、学习目标、项目或约束。"
                "只有用户明确要求记住或信息确实长期稳定时调用。"
                "不要保存密码、API Key、访问令牌或其他认证秘密。"
                "短小的 preference/profile 记忆可能被安全投影为结构化画像；"
                "项目详情和一般记忆仍只按需检索。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_key": {
                        "type": "string",
                        "description": "稳定、可复用的记忆键，例如 preferred_code_language",
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
                        "description": "记忆分类",
                        "default": "general",
                    },
                },
                "required": ["memory_key", "content"],
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

    memory_key = memory_key.strip()
    content = content.strip()
    category = category.strip().lower() or "general"
    if not memory_key or not content:
        return {
            "saved": False,
            "memory_key": memory_key,
            "content": content,
            "category": category,
            "reason": "memory_key/content 不能为空",
        }

    previous = core_memory.get(user_name, memory_key)
    saved = core_memory.set(
        user_name=user_name,
        memory_key=memory_key,
        content=content,
        category=category,
    )
    stored = core_memory.get(user_name, memory_key) if saved else None

    projection = None
    if stored is not None:
        projection = _project_saved_memory(user_name, stored, previous)

    return {
        "saved": saved,
        "memory_key": memory_key,
        "content": content,
        "category": category,
        "profile_projection": projection,
    }


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "search_core_memories",
            "description": (
                "按需检索与当前任务相关的少量长期核心记忆。"
                "仅当当前问题确实依赖过去的偏好、目标、项目、约束或已记住事实时调用；"
                "不要在每轮对话开始时例行调用。isolated 会话不可读取。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要检索的具体主题",
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
                "isolated 会话不可读取。"
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
                "删除当前用户的一条核心记忆。只有用户明确要求忘掉某条记忆时才能调用；"
                "no_write/isolated 会话不可删除。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_key": {
                        "type": "string",
                        "description": "需要删除的记忆名称",
                    }
                },
                "required": ["memory_key"],
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

    memory_key = memory_key.strip()
    existing = core_memory.get(user_name, memory_key)
    deleted = core_memory.delete(user_name=user_name, memory_key=memory_key)

    projection = None
    if deleted and existing is not None:
        projection = _remove_memory_projection(user_name, existing)

    return {
        "deleted": deleted,
        "memory_key": memory_key,
        "profile_projection": projection,
    }
