"""Compile and bind the exact capabilities visible during an agent turn."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

from backend.agent.skills.catalog import ScopedSkillView
from backend.agent.tools import tr
from backend.agent.tools.catalog import (
    ScopedToolView,
    TOOL_RESOURCE_REQUIREMENTS,
    capability_declaration,
)
from backend.agent.tools.context import ToolExecutionContext
from backend.agent.workspaces.models import ResolvedCapabilities


MEMORY_READ_TOOLS = frozenset({"search_core_memories", "get_core_memories"})
MEMORY_WRITE_TOOLS = frozenset(
    {"save_core_memory", "propose_core_memory", "delete_core_memory"}
)
RESEARCH_WORKFLOW_TOOLS = frozenset(
    {"start_frontier_tracking", "start_research_writing", "start_dataset_analysis"}
)
ATTACHMENT_TOOLS = frozenset(
    {
        "parse_pdf_attachment",
        "parse_word_attachment",
        "parse_presentation_attachment",
        "parse_spreadsheet_attachment",
        "parse_image_attachment",
    }
)


class BoundToolExecutor:
    def __init__(
        self,
        view: ScopedToolView,
        skills: ScopedSkillView,
        context: ToolExecutionContext,
    ) -> None:
        self._view = view
        self._skills = skills
        self.context = context

    @property
    def names(self) -> frozenset[str]:
        return self._view.names

    async def execute(self, name: str, arguments: Mapping[str, Any]) -> Any:
        if not self._view.contains(name):
            return {
                "ok": False,
                "error": "tool_not_available",
                "tool": name,
            }
        try:
            normalized = self._view.normalize_arguments(name, arguments)
        except (KeyError, ValueError) as error:
            return {
                "ok": False,
                "error": "invalid_tool_arguments",
                "tool": name,
                "detail": str(error),
            }
        required = TOOL_RESOURCE_REQUIREMENTS.get(name, frozenset())
        effective_capabilities = set(self.context.authorized_resources.capabilities)
        if self.context.authorized_resources.project_id:
            effective_capabilities.add("research_project")
        if self.context.authorized_resources.attachment_ids:
            effective_capabilities.add("attachments")
        if not required <= effective_capabilities:
            return {
                "ok": False,
                "error": "resource_capability_required",
                "tool": name,
                "required": sorted(required),
            }
        if name == "load_skill":
            requested = normalized.get("name")
            if not isinstance(requested, str):
                return {"ok": False, "error": "invalid_skill_name"}
            return self._skills.load(requested)
        if name in {
            "search_core_memories", "get_core_memories",
            "save_core_memory", "propose_core_memory", "delete_core_memory",
        } and self.context.runtime_dependencies.core_memory_service is not None:
            from backend.agent.tools.common.memory_tools import execute_memory_tool

            return execute_memory_tool(self.context, name, normalized)
        if name == "get_teaching_context":
            reader = self.context.runtime_dependencies.teaching_context_reader
            if reader is None:
                raise RuntimeError("Teaching context reader is not configured")
            return reader.read_teaching_context(
                user_id=self.context.user_id,
                class_id=self.context.authorized_resources.class_id,
                assignment_id=self.context.authorized_resources.assignment_id,
            )
        if name in {
            "start_frontier_tracking", "start_research_writing", "start_dataset_analysis"
        }:
            declaration = capability_declaration(name)
            service = self.context.runtime_dependencies.agent_action_service
            if service is None:
                raise RuntimeError("Agent Action service is not configured")
            project_id = self.context.authorized_resources.project_id
            payload = dict(normalized)
            if name == "start_frontier_tracking":
                if project_id is None:
                    raise ValueError("research conversation is not bound to a project")
                payload["project_id"] = project_id
            return service.request(
                user_id=self.context.user_id,
                conversation_id=self.context.conversation_id,
                workspace_type=self.context.workspace_route.workspace_type,
                action_type=name,
                arguments=payload,
                resource_snapshot={
                    "project_id": project_id,
                    "markers": self.context.authorized_resources.markers,
                    "resource_revisions": dict(
                        self.context.authorized_resources.revision_set
                    ),
                    "resource_policy_version": (
                        self.context.authorized_resources.policy_version
                    ),
                    "audit_markers": self.context.authorized_resources.audit_markers,
                    "request_id": self.context.request_id,
                    "run_id": self.context.run_id,
                },
                policy_id=self.context.workspace_route.action_policy,
                approval_mode=declaration.approval_mode,
            )
        if name.startswith("parse_") and name.endswith("_attachment"):
            from backend.agent.tools.common.attachment_tools import execute_attachment_tool

            return await execute_attachment_tool(self.context, name, normalized)
        if name in {
            "recommend_practice", "get_mastery_report", "get_mastery_level",
            "get_weak_prerequisites", "get_review_timing", "record_answer",
            "record_learning_evidence", "get_learning_evidence_summary",
        }:
            from backend.agent.tools.learning.runtime import execute_learning_tool

            return execute_learning_tool(self.context, name, normalized)
        return await self._view.execute(name, normalized)


@dataclass(frozen=True, slots=True)
class CompiledCapabilityView:
    capabilities: ResolvedCapabilities
    skills: ScopedSkillView
    tools: ScopedToolView

    def bind(self, context: ToolExecutionContext) -> BoundToolExecutor:
        return BoundToolExecutor(self.tools, self.skills, context)


class CapabilityRuntime:
    def compile(
        self,
        *,
        skill_scopes: frozenset[str],
        tool_scopes: frozenset[str],
        profile_fingerprint: str,
        policy_versions: tuple[str, ...],
        resource_capabilities: frozenset[str] | None = None,
        conversation_mode: str = "normal",
        has_research_project: bool | None = None,
        has_attachments: bool | None = None,
    ) -> CompiledCapabilityView:
        if conversation_mode not in {"normal", "no_write", "isolated"}:
            raise ValueError("invalid conversation mode")
        excluded_tools = set()
        if conversation_mode == "isolated":
            excluded_tools.update(MEMORY_READ_TOOLS | MEMORY_WRITE_TOOLS)
        elif conversation_mode == "no_write":
            excluded_tools.update(MEMORY_WRITE_TOOLS)
        if has_research_project is False:
            excluded_tools.update(RESEARCH_WORKFLOW_TOOLS)
        if has_attachments is False:
            excluded_tools.update(ATTACHMENT_TOOLS)
        tools = ScopedToolView.compile(
            tr,
            tool_scopes,
            excluded_names=frozenset(excluded_tools),
            resource_capabilities=resource_capabilities,
        )
        skills = ScopedSkillView.compile(skill_scopes, tool_names=tools.names)
        material = "|".join(
            (
                profile_fingerprint,
                f"conversation_mode:{conversation_mode}",
                f"research_project:{has_research_project}",
                f"attachments:{has_attachments}",
                skills.fingerprint,
                tools.fingerprint,
                *sorted(policy_versions),
                *(
                    f"capability:{item}"
                    for item in sorted(resource_capabilities or frozenset())
                ),
            )
        )
        fingerprint = hashlib.sha256(material.encode("utf-8")).hexdigest()
        resolved = ResolvedCapabilities(
            skill_index=skills.build_index(),
            autoload_skills=skills.build_autoload(),
            tool_schemas=tuple(tools.schemas),
            skill_names=skills.names,
            tool_names=tools.names,
            fingerprint=fingerprint,
            action_names=frozenset(
                name
                for name in tools.names
                if capability_declaration(name).kind == "action"
            ),
        )
        return CompiledCapabilityView(resolved, skills, tools)
