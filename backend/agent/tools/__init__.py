# backend/agent/tools/__init__.py

from backend.agent.tools import (
    arxiv_search,  # 触发注册  # noqa: E402, F401
    bitwise_calculator,  # noqa: E402, F401
    calculator,  # noqa: E402, F401
    math_solver,  # noqa: E402, F401
    memory_tools,  # noqa: E402, F401
    skills,  # noqa: E402, F401
    web_search,  # noqa: E402, F401
)
from backend.agent.rag import rag_tool  # RAG 工具注册  # noqa: E402, F401
from backend.agent.tools.tools import tr  # noqa: E402, F401

__all__ = ["tr"]
