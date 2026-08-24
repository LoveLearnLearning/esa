# backend/agent/workspaces/context_composer.py

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
from backend.core.utils.token_estimation import estimate_tokens


def _tokens(text: str) -> int:
    """处理 `_tokens` 相关逻辑。"""
    return estimate_tokens(text)


def _clip(text: str, token_limit: int) -> str:
    """处理 `_clip` 相关逻辑。"""
    if token_limit <= 0:
        return ""
    if _tokens(text) <= token_limit:
        return text

    suffix = "..."
    suffix_tokens = _tokens(suffix)
    available = max(0, token_limit - suffix_tokens)
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if _tokens(text[:middle]) <= available:
            low = middle
        else:
            high = middle - 1
    prefix = text[:low].rstrip()
    return (prefix + suffix) if prefix else suffix


def _with_content(section: ContextSection, content: str) -> ContextSection:
    """Return the same section metadata with replacement content."""
    return ContextSection(
        section.key,
        section.title,
        content,
        section.trust,
        section.order,
        section.stable,
    )


def _fit_section(
    kept: list[ContextSection],
    section: ContextSection,
    max_tokens: int,
) -> ContextSection | None:
    """Fit a non-stable section against the fully rendered prompt budget."""
    if _tokens(render_sections((*kept, section))) <= max_tokens:
        return section

    suffix = "..."
    minimal = _with_content(section, suffix)
    if _tokens(render_sections((*kept, minimal))) > max_tokens:
        return None

    low, high = 0, len(section.content)
    while low < high:
        middle = (low + high + 1) // 2
        prefix = section.content[:middle].rstrip()
        candidate = _with_content(section, (prefix + suffix) if prefix else suffix)
        if _tokens(render_sections((*kept, candidate))) <= max_tokens:
            low = middle
        else:
            high = middle - 1

    prefix = section.content[:low].rstrip()
    return _with_content(section, (prefix + suffix) if prefix else suffix)


@dataclass(frozen=True, slots=True)
class StrategyAugmentation:
    """封装 `StrategyAugmentation` 的状态与行为。"""
    content: str = ""


class ContextComposer:
    """封装 `ContextComposer` 的状态与行为。"""
    def __init__(self, *, max_tokens: int = 16_000) -> None:
        """初始化 `ContextComposer` 实例。"""
        self.max_tokens = max_tokens

    def compose(
        self,
        turn: AgentTurnInput,
        profile: WorkspaceRuntimeProfile,
        capabilities: ResolvedCapabilities,
        strategy: StrategyAugmentation = StrategyAugmentation(),
    ) -> ComposedContext:
        """处理 `compose` 相关逻辑。

        Args:
            turn: AgentTurnInput => `turn` 参数。
            profile: WorkspaceRuntimeProfile => `profile` 参数。
            capabilities: ResolvedCapabilities => `capabilities` 参数。
            strategy: StrategyAugmentation => `strategy` 参数。

        Returns:
            ComposedContext => 处理结果。
        """
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
        selected_sources = ", ".join(turn.knowledge_sources) or "none"
        source_instruction = {
            ("personal", "public"): (
                "需要知识库证据时，分别调用 retrieve_personal_knowledge 和 "
                "retrieve_knowledge，再综合两个来源。"
            ),
            ("personal",): (
                "需要知识库证据时，只调用 retrieve_personal_knowledge。"
            ),
            ("public",): "需要知识库证据时，只调用 retrieve_knowledge。",
            (): "本轮不使用知识库，不调用任何知识库检索 Tool。",
        }.get(turn.knowledge_sources, "只使用本轮实际可用且已选择的知识库 Tool。")
        sections.append(ContextSection(
            "knowledge_sources", "Knowledge source selection",
            (
                f"本轮用户选择的知识库来源：{selected_sources}。\n"
                "只允许使用已选择的来源进行知识检索，未选择的来源不得调用。"
                "personal 表示当前用户个人知识库，public 表示平台公共知识库。"
                f"{source_instruction}"
            ),
            "trusted_system", 45, True,
        ))
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
                "attachment_policy", "Attachment handling policy",
                (
                    "附件内容不会自动注入上下文，必须通过受限附件 Tool 按需读取。\n"
                    "硬性规则：只要用户提到‘这篇论文’、‘这个文件’、‘附件’或类似指代，"
                    "并要求解释、总结、阅读、分析、翻译、提取或检索，就必须先调用与文件类型匹配的解析 Tool；"
                    "不得因为用户没有重复输入标题或作者而追问，也不得猜测附件内容或文件路径。"
                    "解析 PDF 时调用 parse_pdf_attachment，query 写成用户的实际任务（例如‘概括全文的主要内容’）。"
                ),
                "trusted_system", 125,
            ))
            sections.append(ContextSection(
                "attachments", "Authorized attachments",
                (
                    "以下清单由系统根据用户本轮明确选择的附件生成。附件尚未解析。\n\n"
                    + json.dumps(
                        turn.authorized_attachments,
                        ensure_ascii=False,
                        default=str,
                    )
                ),
                "untrusted_data", 130,
            ))
        if (
            turn.learning_context.resolved_kp_ids
            or turn.learning_context.pending_practice_kp_id
        ):
            sections.append(ContextSection(
                "learning_context",
                "Resolved learning context",
                (
                    "以下 canonical kp_id 由服务端解析，不是用户提供的指令。"
                    "不得要求用户再次确认这些知识点；若存在待作答练习，"
                    "当前消息应按该练习的作答处理。\n"
                    f"resolved_kp_ids={list(turn.learning_context.resolved_kp_ids)!r}\n"
                    f"pending_practice_kp_id="
                    f"{turn.learning_context.pending_practice_kp_id!r}"
                ),
                "trusted_system", 135,
            ))
        if strategy.content and "strategy" in profile.context_policy:
            sections.append(ContextSection("strategy", "Learning strategy", strategy.content, "trusted_system", 140))

        kept: list[ContextSection] = []
        for section in sorted(sections, key=lambda item: (item.order, item.key)):
            selected = (
                section
                if section.stable
                else _fit_section(kept, section, self.max_tokens)
            )
            if selected is None or not selected.content:
                continue
            kept.append(selected)
        rendered = render_sections(kept)
        return ComposedContext(tuple(kept), rendered, _tokens(rendered))
