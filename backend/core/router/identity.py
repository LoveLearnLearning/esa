# backend/core/router/identity.py

"""Conversion from authentication records to trusted routing identity."""

from __future__ import annotations

from backend.core.router.errors import WorkspaceAccessDenied
from backend.core.router.models import TrustedIdentity
from backend.core.utils.models import SessionPrincipal, UserRecord


def resolve_identity(
    principal: SessionPrincipal,
    user: UserRecord,
) -> TrustedIdentity:
    """解析 `identity` 相关数据。

    Args:
        principal: SessionPrincipal => `principal` 参数。
        user: UserRecord => `user` 参数。

    Returns:
        TrustedIdentity => 处理结果。
    """
    if principal.user_id != user.id:
        raise WorkspaceAccessDenied("session and user identity do not match")
    if user.status != "active":
        raise WorkspaceAccessDenied("user account is not active")
    return TrustedIdentity(
        user_id=user.id,
        username=user.username,
        account_role=user.account_role,
        status=user.status,
    )
