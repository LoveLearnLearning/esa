"""Authorized resource context accepted by the core router."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConversationContext:
    conversation_id: str
    user_id: str
    workspace_type: str
    research_project_id: str | None = None
    class_id: str | None = None
    assignment_id: str | None = None


@dataclass(frozen=True, slots=True)
class AttachmentAuthorization:
    attachment_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RoutingContext:
    conversation: ConversationContext
    attachments: AttachmentAuthorization = AttachmentAuthorization()
    project_owned: bool = False
    class_authorized: bool = False
    assignment_authorized: bool = False
    resource_capabilities: frozenset[str] = frozenset()

