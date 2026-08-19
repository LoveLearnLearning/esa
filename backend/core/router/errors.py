# backend/core/router/errors.py

"""Domain errors emitted by the core router."""


class WorkspaceRoutingError(RuntimeError):
    """Base class for fail-closed routing failures."""


class WorkspaceAccessDenied(WorkspaceRoutingError):
    """封装 `WorkspaceAccessDenied` 的状态与行为。"""
    pass


class ResourceAccessDenied(WorkspaceRoutingError):
    """封装 `ResourceAccessDenied` 的状态与行为。"""
    pass


class RouteProfileMismatch(WorkspaceRoutingError):
    """封装 `RouteProfileMismatch` 的状态与行为。"""
    pass


class InvalidRoutingContext(WorkspaceRoutingError):
    """封装 `InvalidRoutingContext` 的状态与行为。"""
    pass
