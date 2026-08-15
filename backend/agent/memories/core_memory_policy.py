# backend/agent/memories/core_memory_policy.py

"""CoreMemory permission and content policy."""

from __future__ import annotations

import re

from backend.agent.memories.core_memory_models import MemoryPolicyDenied, MemoryScope
from backend.agent.tools.context import ToolExecutionContext

_SENSITIVE = re.compile(
    r"(?i)(password|passwd|验证码|session\s*id|api[_ -]?key|access[_ -]?token|"
    r"refresh[_ -]?token|cookie|private[_ -]?key|银行卡|信用卡)"
)


class CoreMemoryPolicy:
    """封装 `CoreMemoryPolicy` 的状态与行为。"""
    def ensure_read(self, context: ToolExecutionContext) -> None:
        """确保 `read` 相关数据。"""
        if context.conversation_mode == "isolated":
            raise MemoryPolicyDenied("isolated conversation cannot read memory")

    def ensure_write(self, context: ToolExecutionContext) -> None:
        """确保 `write` 相关数据。"""
        if context.conversation_mode != "normal":
            raise MemoryPolicyDenied("conversation mode does not permit memory writes")

    def resolve_scope(
        self,
        context: ToolExecutionContext,
        scope_type: str,
    ) -> MemoryScope:
        """解析 `scope` 相关数据。

        Args:
            context: ToolExecutionContext => `context` 参数。
            scope_type: str => `scope_type` 参数。

        Returns:
            MemoryScope => 处理结果。
        """
        if scope_type == "global":
            return MemoryScope("global")
        if scope_type == "workspace":
            return MemoryScope("workspace", context.workspace_route.workspace_type)
        raise MemoryPolicyDenied("invalid memory scope")

    def visible_scopes(self, context: ToolExecutionContext) -> tuple[MemoryScope, ...]:
        """处理 `visible_scopes` 相关逻辑。"""
        self.ensure_read(context)
        return (
            MemoryScope("global"),
            MemoryScope("workspace", context.workspace_route.workspace_type),
        )

    def validate_content(self, context: ToolExecutionContext, content: str) -> str:
        """校验 `content` 相关数据。

        Args:
            context: ToolExecutionContext => `context` 参数。
            content: str => 待处理内容。

        Returns:
            str => 处理结果。
        """
        normalized = " ".join(content.split()).strip()
        if not normalized:
            raise ValueError("memory content cannot be empty")
        if len(normalized) > 4000:
            raise ValueError("memory content is too long")
        if _SENSITIVE.search(normalized):
            raise MemoryPolicyDenied("sensitive credentials cannot be stored")
        workspace = context.workspace_route.workspace_type
        if workspace == "teaching" and re.search(r"学生.{0,8}(病|家庭|电话|住址|身份证)", normalized):
            raise MemoryPolicyDenied("student private data cannot enter teacher memory")
        return normalized
