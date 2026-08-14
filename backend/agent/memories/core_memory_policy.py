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
    def _settings(self, context: ToolExecutionContext):
        store = context.runtime_dependencies.user_store
        if store is None:
            return None
        return store.get_memory_settings(context.user_id)

    def ensure_read(self, context: ToolExecutionContext) -> None:
        if context.conversation_mode == "isolated":
            raise MemoryPolicyDenied("isolated conversation cannot read memory")
        settings = self._settings(context)
        if settings is not None and not settings.saved_memory_enabled:
            raise MemoryPolicyDenied("saved memory is disabled")

    def ensure_write(self, context: ToolExecutionContext) -> None:
        if context.conversation_mode != "normal":
            raise MemoryPolicyDenied("conversation mode does not permit memory writes")
        settings = self._settings(context)
        if settings is not None and not settings.saved_memory_enabled:
            raise MemoryPolicyDenied("saved memory is disabled")

    def resolve_scope(
        self,
        context: ToolExecutionContext,
        scope_type: str,
    ) -> MemoryScope:
        if scope_type == "global":
            return MemoryScope("global")
        if scope_type == "workspace":
            return MemoryScope("workspace", context.workspace_route.workspace_type)
        raise MemoryPolicyDenied("invalid memory scope")

    def visible_scopes(self, context: ToolExecutionContext) -> tuple[MemoryScope, ...]:
        self.ensure_read(context)
        return (
            MemoryScope("global"),
            MemoryScope("workspace", context.workspace_route.workspace_type),
        )

    def validate_content(self, context: ToolExecutionContext, content: str) -> str:
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
