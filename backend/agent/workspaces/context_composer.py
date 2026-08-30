# backend/agent/workspaces/context_composer.py

"""Pure deterministic context composition."""

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


@dataclass(frozen=True, slots=True)
class StrategyAugmentation:
    """封装 `StrategyAugmentation` 的状态与行为。"""
    content: str = ""


class ContextComposer:
    """封装 `ContextComposer` 的状态与行为。"""
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
        selected_sources = ",".join(turn.knowledge_sources) or "none"
        source_instruction = {
            ("personal", "public"): "retrieve_knowledge 将检索两类来源并统一排序。",
            ("personal",): "retrieve_knowledge 仅检索当前用户获授权的个人库。",
            ("public",): "retrieve_knowledge 仅检索公共库。",
            (): "禁止调用知识库检索 Tool。",
        }.get(turn.knowledge_sources, "retrieve_knowledge 仅检索实际列出的来源。")
        sections.append(ContextSection(
            "knowledge_sources", "Knowledge source selection",
            (
                f"sources={selected_sources}；personal=个人库，public=公共库。"
                f"未选来源不得调用；{source_instruction}"
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
            profile_content = ""
            if callable(to_prompt_json):
                try:
                    profile_content = to_prompt_json(
                        current_message=turn.current_message,
                        task_mode=turn.task_mode,
                        resolved_kp_ids=turn.learning_context.resolved_kp_ids,
                    )
                except TypeError:
                    # Compatibility for lightweight test/extension snapshots with
                    # the historical zero-argument projection method.
                    profile_content = to_prompt_json()
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
                turn.conversation_summary,
                "untrusted_data",
                120,
            ))
        if turn.authorized_attachments and "attachments" in profile.context_policy:
            sections.append(ContextSection(
                "attachment_policy", "Attachment handling policy",
                (
                    "当前对话中的全部已授权附件都可以在后续轮次继续使用。"
                    "历史消息中的 attachment_id 只有出现在下方清单中才可调用。"
                    "如果用户要求比较多个文件，应分别解析相关文件后再回答。"
                    "清单中有附件且用户要求阅读、总结、解释、翻译、提取或检索时，"
                    "必须在回复前调用对应解析 Tool 获取内容后再回答。"
                    "不追问 Tool 已有标识，不猜内容或路径。"
                ),
                "trusted_system", 125,
            ))
            sections.append(ContextSection(
                "attachments", "Authorized attachments",
                (
                    "当前对话中系统授权、仍存在且尚未解析的附件：\n"
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

        kept = [
            section
            for section in sorted(sections, key=lambda item: (item.order, item.key))
            if section.content
        ]
        rendered = render_sections(kept)
        return ComposedContext(tuple(kept), rendered, _tokens(rendered))
