# backend/core/router/models.py

"""Compatibility exports for Agent-owned trusted routing contracts."""

from backend.agent.workspaces.routing import (
    ResourceScope,
    TrustedIdentity,
    WorkspaceRoute,
    WorkspaceType,
)

__all__ = ["ResourceScope", "TrustedIdentity", "WorkspaceRoute", "WorkspaceType"]
