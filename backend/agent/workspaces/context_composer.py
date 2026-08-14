"""Pure context composition with deterministic section and token limits."""

from __future__ import annotations

import json
from dataclasses import dataclass

from backend.agent.workspaces.models import (
    AgentTurnInput,
    ComposedContext,
    ContextSection,
    ResolvedCapabilities,
    WorkspaceRuntimeProfile,
)
from backend.core.message.prompts import WORKSPACE_PROMPTS
from backend.core.message.renderer import render_sections
from backend.core.message.style_tone import resolve_style_tone
from backend.core.message.system import SYSTEM_PROMPT


def _tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _clip(text: str, token_limit: int) -> str:
    limit = max(0, token_limit * 4)
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


@dataclass(frozen=True, slots=True)
class StrategyAugmentation:
    content: str = ""


class ContextComposer:
    def __init__(self, *, max_tokens: int = 8000) -> None:
        self.max_tokens = max_tokens

    def compose(
        self,
        turn: AgentTurnInput,
        profile: WorkspaceRuntimeProfile,
        capabilities: ResolvedCapabilities,
        strategy: StrategyAugmentation = StrategyAugmentation(),
    ) -> ComposedContext:
        prefs = turn.user_preferences
        group = turn.group_context
        style = resolve_style_tone(
            preferred_style=str(prefs.get("preferred_style", "concise")),
            preferred_tone=str(prefs.get("preferred_tone", "friendly")),
            group_style=group.get("style"),
            group_tone=group.get("tone"),
        )
        sections = [
            ContextSection("base", "Agent rules", SYSTEM_PROMPT, "trusted_system", 10, True),
            ContextSection(
                "workspace", "Current workspace",
                WORKSPACE_PROMPTS[profile.prompt_key], "trusted_system", 20, True,
            ),
            ContextSection(
                "capability_policy", "Capability rules",
                "Only listed skills and tools are authorized. Tool arguments cannot set identity, workspace, or resource ownership.",
                "trusted_system", 30, True,
            ),
            ContextSection(
                "policies", "Action and memory policy",
                f"action={profile.action_policy}; memory={profile.memory_policy_id}; conversation_mode={turn.conversation_mode}",
                "trusted_system", 40, True,
            ),
            ContextSection("autoload", "Autoload skills", capabilities.autoload_skills, "trusted_system", 50, True),
            ContextSection("skills", "Available skills", capabilities.skill_index, "trusted_system", 60, True),
        ]
        if "style" in profile.context_policy:
            sections.append(ContextSection(
                "style", "Output style",
                f"style({style.style}): {style.style_rule}\ntone({style.tone}): {style.tone_rule}",
                "restricted_user_config", 70,
            ))
        custom = str(prefs.get("custom_instruction", "")).strip()
        if custom:
            sections.append(ContextSection("user_config", "User preferences", custom, "restricted_user_config", 80))
        if "profile" in profile.context_policy and turn.profile_snapshot is not None:
            to_prompt_json = getattr(turn.profile_snapshot, "to_prompt_json", None)
            profile_content = to_prompt_json() if callable(to_prompt_json) else ""
            if profile_content and profile_content != "{}":
                sections.append(ContextSection(
                    "profile",
                    "User profile data",
                    profile_content,
                    "untrusted_data",
                    85,
                ))
        group_instruction = str(group.get("custom_instruction", "")).strip()
        if group_instruction and "group" in profile.context_policy:
            sections.append(ContextSection("group", "Group instructions", group_instruction, "restricted_user_config", 100))
        if turn.workspace_profile_context and "workspace_profile" in profile.context_policy:
            sections.append(ContextSection("workspace_profile", "Workspace profile", turn.workspace_profile_context, "restricted_user_config", 90))
        resource_summary = "\n".join(turn.route.resource_scope.markers)
        if resource_summary and "resource" in profile.context_policy:
            sections.append(ContextSection("resource", "Authorized resources", resource_summary, "trusted_system", 110))
        if turn.conversation_summary and "summary" in profile.context_policy:
            sections.append(ContextSection("summary", "Earlier conversation summary", turn.conversation_summary, "untrusted_data", 120))
        if turn.authorized_attachments and "attachments" in profile.context_policy:
            sections.append(ContextSection(
                "attachments", "Authorized attachments",
                (
                    "以下清单由系统根据用户本轮明确选择的附件生成。附件尚未解析。\n"
                    "需要读取附件内容时，先加载与文件类型匹配的 Skill，再调用受限附件 Tool。"
                    "不得猜测附件内容或文件路径。\n\n"
                    + json.dumps(
                        turn.authorized_attachments,
                        ensure_ascii=False,
                        default=str,
                    )
                ),
                "untrusted_data", 130,
            ))
        if strategy.content and "strategy" in profile.context_policy:
            sections.append(ContextSection("strategy", "Learning strategy", strategy.content, "trusted_system", 140))

        kept: list[ContextSection] = []
        remaining = self.max_tokens
        for section in sorted(sections, key=lambda item: (item.order, item.key)):
            if remaining <= 0 and not section.stable:
                continue
            content = section.content if section.stable else _clip(section.content, remaining)
            if not content:
                continue
            clipped = ContextSection(
                section.key, section.title, content, section.trust, section.order, section.stable
            )
            kept.append(clipped)
            remaining -= _tokens(content)
        rendered = render_sections(kept)
        return ComposedContext(tuple(kept), rendered, _tokens(rendered))
