# backend/core/router/context.py

"""Authorized resource context accepted by the core router."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConversationContext:
    """封装 `ConversationContext` 的状态与行为。"""
    conversation_id: str
    user_id: str
    workspace_type: str
    research_project_id: str | None = None
    class_id: str | None = None
    assignment_id: str | None = None


@dataclass(frozen=True, slots=True)
class AttachmentAuthorization:
    """封装 `AttachmentAuthorization` 的状态与行为。"""
    attachment_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RoutingContext:
    """封装 `RoutingContext` 的状态与行为。"""
    conversation: ConversationContext
    attachments: AttachmentAuthorization = AttachmentAuthorization()
    project_owned: bool = False
    class_authorized: bool = False
    assignment_authorized: bool = False
    resource_capabilities: frozenset[str] = frozenset()
