# backend/agent/memories/core_memory_models.py

"""CoreMemory V2 domain models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

ScopeType: TypeAlias = Literal["global", "workspace"]
MemoryStatus: TypeAlias = Literal["active", "suppressed"]


@dataclass(frozen=True, slots=True)
class MemoryScope:
    """封装 `MemoryScope` 的状态与行为。"""
    scope_type: ScopeType
    workspace_type: str | None = None

    def __post_init__(self) -> None:
        """完成实例初始化后的校验与派生字段构建。"""
        if self.scope_type == "global" and self.workspace_type is not None:
            raise ValueError("global scope cannot include workspace_type")
        if self.scope_type == "workspace" and self.workspace_type not in {
            "learning", "teaching", "research"
        }:
            raise ValueError("workspace scope requires a valid workspace_type")


@dataclass(frozen=True, slots=True)
class CoreMemoryRecord:
    """表示 `core memory record` 数据结构。"""
    memory_id: str
    user_id: str
    memory_key: str
    content: str
    category: str
    scope: MemoryScope
    status: MemoryStatus
    source_type: str
    revision: int
    confirmed_at: str | None
    review_after: str | None
    expires_at: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        """将当前对象转换为字典。"""
        return {
            "memory_id": self.memory_id,
            "user_id": self.user_id,
            "memory_key": self.memory_key,
            "content": self.content,
            "category": self.category,
            "scope_type": self.scope.scope_type,
            "workspace_type": self.scope.workspace_type,
            "status": self.status,
            "source_type": self.source_type,
            "revision": self.revision,
            "confirmed_at": self.confirmed_at,
            "review_after": self.review_after,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """封装 `MemoryCandidate` 的状态与行为。"""
    candidate_id: str
    user_id: str
    memory_id: str | None
    memory_key: str
    proposed_content: str | None
    category: str
    scope: MemoryScope
    candidate_type: str
    status: str
    expected_revision: int | None
    resulting_memory_id: str | None
    created_at: str
    decided_at: str | None
    expires_at: str

    def to_dict(self) -> dict[str, object]:
        """将当前对象转换为字典。"""
        return {
            "candidate_id": self.candidate_id,
            "memory_id": self.memory_id,
            "memory_key": self.memory_key,
            "proposed_content": self.proposed_content,
            "category": self.category,
            "scope_type": self.scope.scope_type,
            "workspace_type": self.scope.workspace_type,
            "candidate_type": self.candidate_type,
            "status": self.status,
            "expected_revision": self.expected_revision,
            "resulting_memory_id": self.resulting_memory_id,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
            "expires_at": self.expires_at,
        }


class MemoryRevisionConflict(RuntimeError):
    """表示 `MemoryRevisionConflict` 异常。"""
    def __init__(self, current_revision: int) -> None:
        """初始化 `MemoryRevisionConflict` 实例。"""
        super().__init__(f"memory revision conflict: current={current_revision}")
        self.current_revision = current_revision


class MemoryPolicyDenied(PermissionError):
    """封装 `MemoryPolicyDenied` 的状态与行为。"""
    pass
