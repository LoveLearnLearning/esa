"""Domain errors emitted by the core router."""


class WorkspaceRoutingError(RuntimeError):
    """Base class for fail-closed routing failures."""


class WorkspaceAccessDenied(WorkspaceRoutingError):
    pass


class ResourceAccessDenied(WorkspaceRoutingError):
    pass


class RouteProfileMismatch(WorkspaceRoutingError):
    pass


class InvalidRoutingContext(WorkspaceRoutingError):
    pass

