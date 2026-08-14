# backend/core/router/basic_router.py
"""Fail-closed routing for trusted identity and authorized resources."""

from __future__ import annotations

from backend.core.router.context import RoutingContext
from backend.core.router.errors import InvalidRoutingContext, ResourceAccessDenied
from backend.core.router.models import ResourceScope, TrustedIdentity, WorkspaceRoute
from backend.core.router.workspace_profiles import build_workspace_route
from backend.core.router.workspace_registry import resolve_workspace


class CoreRouter:
    def route(
        self,
        identity: TrustedIdentity,
        context: RoutingContext,
    ) -> WorkspaceRoute:
        conversation = context.conversation
        if conversation.user_id != identity.user_id:
            raise ResourceAccessDenied("conversation does not belong to identity")
        if not conversation.conversation_id:
            raise InvalidRoutingContext("conversation_id is required")

        registration = resolve_workspace(identity, conversation.workspace_type)
        workspace = registration.workspace_type
        if workspace != "research" and conversation.research_project_id:
            raise InvalidRoutingContext("research project requires research workspace")
        if workspace == "research" and conversation.research_project_id:
            if not context.project_owned:
                raise ResourceAccessDenied("research project is not authorized")
        if workspace not in {"learning", "teaching"} and (
            conversation.class_id or conversation.assignment_id
        ):
            raise InvalidRoutingContext(
                "classroom binding requires learning or teaching workspace"
            )
        if conversation.class_id and not context.class_authorized:
            raise ResourceAccessDenied("classroom is not authorized")
        if conversation.assignment_id and not context.assignment_authorized:
            raise ResourceAccessDenied("assignment is not authorized")

        capabilities = set(context.resource_capabilities)
        if conversation.research_project_id:
            capabilities.add("research_project")
        if context.attachments.attachment_ids:
            capabilities.add("attachments")
        if conversation.class_id:
            capabilities.add("classroom")
        if conversation.assignment_id:
            capabilities.add("assignment")
        resource_scope = ResourceScope(
            project_id=conversation.research_project_id,
            class_id=conversation.class_id,
            assignment_id=conversation.assignment_id,
            attachment_ids=context.attachments.attachment_ids,
            capabilities=frozenset(capabilities),
        )
        return build_workspace_route(registration, resource_scope)


def route_workspace(
    identity: TrustedIdentity,
    context: RoutingContext,
) -> WorkspaceRoute:
    return CoreRouter().route(identity, context)
