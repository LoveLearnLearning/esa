# backend/agent/workspaces/context_composer.py

"""Pure context composition with deterministic section and token limits."""

from __future__ import annotations

import json
import re
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
from backend.core.message.budget import DEFAULT_PROMPT_BUDGET
from backend.core.utils.token_estimation import estimate_tokens


TASK_MODE_INSTRUCTIONS = {
    "explain_problem": "识别题目条件与学习者卡点，分步讲解思路和原理。",
    "study_plan": "根据科目、剩余时间与每日可用时间制定可执行计划；信息不足先追问。",
    "search_materials": "优先使用已授权知识库或附件能力，并明确回答依据。",
    "review_homework": "区分题目与学生作答，指出具体错误、原因和修改方法。",
    "concept": "给出通俗定义、正式定义、典型例子、相近概念区别和题目用法。",
    "mastery_report": "使用掌握度能力说明总体掌握度、薄弱点、优势与复习内容。",
    "practice_recommendation": "结合课程、考试时间与掌握度推荐下一步练习。",
    "academic_search": "检索学术资料，区分检索事实、证据与推断。",
    "literature_frontier": "归纳研究热点、发展脉络、代表工作和证据边界。",
    "academic_writing": "围绕文稿类型、主题和目标规范提供结构化写作帮助。",
    "research_data_analysis": "先确认数据、字段和研究问题，再选择合适分析方法。",
    "research_planning": "梳理研究问题、方法、条件、风险和里程碑。",
}


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

    # Structured and executable content must remain whole. Its producer owns
    # field-level projection; dropping the section is safer than invalid JSON or
    # a partially rendered Skill instruction.
    if section.key in {
        "profile",
        "attachments",
        "learning_context",
        "strategy",
    }:
        return None

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


def _project_summary(text: str, token_limit: int = 768) -> str:
    """Bound free-text summaries at sentence/paragraph boundaries."""
    normalized = text.strip()
    if not normalized or _tokens(normalized) <= token_limit:
        return normalized
    pieces = [
        item.strip()
        for item in re.split(r"(?<=[。！？.!?])\s+|\n+", normalized)
        if item.strip()
    ]
    kept: list[str] = []
    for piece in pieces:
        candidate = "\n".join((*kept, piece))
        if _tokens(candidate) > token_limit:
            break
        kept.append(piece)
    return "\n".join(kept)


@dataclass(frozen=True, slots=True)
class StrategyAugmentation:
    """封装 `StrategyAugmentation` 的状态与行为。"""
    content: str = ""


class ContextComposer:
    """封装 `ContextComposer` 的状态与行为。"""
    def __init__(self, *, max_tokens: int = 8000) -> None:
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
                "仅可使用所列 Skill/Tool；参数不能设置身份、Workspace 或资源归属。",
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
            profile_content = (
                to_prompt_json(
                    max_tokens=DEFAULT_PROMPT_BUDGET.profile_max_tokens,
                    current_message=turn.current_message,
                    task_mode=turn.task_mode,
                    resolved_kp_ids=turn.learning_context.resolved_kp_ids,
                )
                if callable(to_prompt_json)
                else ""
            )
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
        if turn.task_mode:
            instruction = TASK_MODE_INSTRUCTIONS.get(turn.task_mode)
            if instruction:
                sections.append(ContextSection(
                    "task_mode", "Selected task mode",
                    f"mode={turn.task_mode}\n{instruction}",
                    "trusted_system", 105,
                ))
        if turn.workspace_profile_context and "workspace_profile" in profile.context_policy:
            sections.append(ContextSection("workspace_profile", "Workspace profile", turn.workspace_profile_context, "restricted_user_config", 90))
        resource_summary = "\n".join(turn.route.resource_scope.markers)
        if resource_summary and "resource" in profile.context_policy:
            sections.append(ContextSection("resource", "Authorized resources", resource_summary, "trusted_system", 110))
        if turn.conversation_summary and "summary" in profile.context_policy:
            sections.append(ContextSection(
                "summary",
                "Earlier conversation summary",
                _project_summary(turn.conversation_summary),
                "untrusted_data",
                120,
            ))
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
