# backend/core/router/__init__.py

"""初始化 `backend.core.router` Python 包。"""

from backend.core.router.basic_router import CoreRouter, route_workspace
from backend.core.router.classroom_authorization import (
    ClassroomAuthorization,
    authorize_classroom_resources,
)
from backend.core.router.context import (
    AttachmentAuthorization,
    ConversationContext,
    RoutingContext,
)
from backend.core.router.identity import resolve_identity
from backend.core.router.models import ResourceScope, TrustedIdentity, WorkspaceRoute

__all__ = [
    "AttachmentAuthorization",
    "ConversationContext",
    "CoreRouter",
    "ClassroomAuthorization",
    "ResourceScope",
    "RoutingContext",
    "TrustedIdentity",
    "WorkspaceRoute",
    "resolve_identity",
    "authorize_classroom_resources",
    "route_workspace",
]
