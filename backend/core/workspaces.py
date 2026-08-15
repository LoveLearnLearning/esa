# backend/core/workspaces.py

"""Workspace catalog and role-based access policy."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, TypeAlias

AccountRole: TypeAlias = Literal["student", "teacher"]
WorkspaceType: TypeAlias = Literal["learning", "teaching", "research"]

VALID_ACCOUNT_ROLES = frozenset({"student", "teacher"})
VALID_WORKSPACE_TYPES = frozenset({"learning", "teaching", "research"})


@dataclass(frozen=True, slots=True)
class WorkspaceDescriptor:
    """封装 `WorkspaceDescriptor` 的状态与行为。"""
    type: WorkspaceType
    name: str
    description: str
    capabilities: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        """转换 `payload` 相关数据。"""
        payload = asdict(self)
        payload["capabilities"] = list(self.capabilities)
        return payload


WORKSPACE_CATALOG: dict[WorkspaceType, WorkspaceDescriptor] = {
    "learning": WorkspaceDescriptor(
        type="learning",
        name="学习空间",
        description="课程学习、练习、课表与知识掌握",
        capabilities=("chat", "schedule", "knowledge_map", "mastery"),
    ),
    "teaching": WorkspaceDescriptor(
        type="teaching",
        name="教学空间",
        description="教学设计与教师工作流",
        capabilities=("chat",),
    ),
    "research": WorkspaceDescriptor(
        type="research",
        name="科研空间",
        description="科研项目、文献、写作、趋势与数据分析",
        capabilities=("chat", "research_projects", "attachments"),
    ),
}

ROLE_WORKSPACES: dict[AccountRole, tuple[WorkspaceType, ...]] = {
    "student": ("learning", "research"),
    "teacher": ("teaching", "research"),
}


class WorkspaceAccessPolicy:
    """封装 `WorkspaceAccessPolicy` 的状态与行为。"""
    @staticmethod
    def allowed_workspaces(account_role: str) -> tuple[WorkspaceType, ...]:
        """处理 `allowed_workspaces` 相关逻辑。"""
        if account_role not in VALID_ACCOUNT_ROLES:
            return ()
        return ROLE_WORKSPACES[account_role]  # type: ignore[index]

    @classmethod
    def can_access(cls, account_role: str, workspace_type: str) -> bool:
        """处理 `can_access` 相关逻辑。

        Args:
            account_role: str => `account_role` 参数。
            workspace_type: str => `workspace_type` 参数。

        Returns:
            bool => 处理结果。
        """
        return workspace_type in cls.allowed_workspaces(account_role)

    @classmethod
    def manifest(cls, account_role: str) -> dict[str, object]:
        """处理 `manifest` 相关逻辑。"""
        allowed = cls.allowed_workspaces(account_role)
        if not allowed:
            raise ValueError(f"unsupported account role: {account_role!r}")
        return {
            "account_role": account_role,
            "default_workspace": allowed[0],
            "workspaces": [WORKSPACE_CATALOG[item].to_payload() for item in allowed],
        }


def workspace_prompt(workspace_type: str) -> str:
    """处理 `workspace_prompt` 相关逻辑。

    Args:
        workspace_type: str => `workspace_type` 参数。

    Returns:
        str => 处理结果。
    """
    prompts = {
        "learning": (
            "当前处于学习空间。围绕课程学习、练习、知识掌握和学习规划提供帮助。"
        ),
        "teaching": (
            "当前处于教学空间。围绕教学设计、课程组织和教师工作提供帮助；"
            "不要把教师任务误判为学生答题。"
        ),
        "research": (
            "当前处于科研空间。围绕科研项目、文献证据、学术写作、前沿趋势"
            "和科研数据提供帮助；明确区分来源事实、分析结论与生成内容。"
        ),
    }
    return prompts.get(workspace_type, prompts["learning"])
