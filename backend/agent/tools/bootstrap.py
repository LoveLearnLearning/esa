"""Explicit registration of built-in tools at application/Agent startup."""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def register_builtin_tools() -> None:
    from backend.agent.tools import (  # noqa: F401
        arxiv_search,
        rag_tool,
        skills,
        web_search,
    )
    from backend.agent.tools.math_tools import (  # noqa: F401
        bitwise_calculator,
        calculator,
        math_solver,
    )
    from backend.agent.tools.research import workflow_tools  # noqa: F401
    from backend.agent.tools.common.attachment_tools import register_attachment_schemas
    from backend.agent.tools.contextual_schemas import register_contextual_schemas

    register_contextual_schemas()
    register_attachment_schemas()
