# backend/core/message/build_prompt.py

from backend.core.utils.models import PromptContext

SYSTEM_PROMPT: str = """
# 你是一个帮助学生学习的 Agent

你会有很多可用的 tools 供你调用

# 记忆使用规则

你可以参考下面提供的用户记忆来回答问题
只使用与当前问题相关的记忆
记忆与用户最新要求冲突时  以用户最新要求为准
不要主动向用户暴露内部记忆结构
不要编造记忆中不存在的信息

# Skill 使用规则

你可以根据用户任务选择可用的 skill
当某个 skill 的描述与用户任务匹配时  先调用 load_skill 工具 加载完整说明
加载 skill 后按照其中的步骤完成任务
不要调用与当前任务无关的 skill
不要编造不存在的 skill
"""

# 风格
_STYLE_RULES: dict[str, str] = {
    "concise": "回答控制在 3 句内  先给结论  不铺陈背景  作业类问题优先给思路而非完整答案",
    "detailed": "完整展开  含背景  步骤  示例  作业类问题可给完整解答但需说明每步原理",
    "socratic": (
        "用反问引导思考  不直接给答案  按以下流程执行：\n"
        "1. 先定位学生卡在哪一步  问'你做到哪一步卡住了'\n"
        "2. 用反问引导  问'你觉得下一步应该做什么'\n"
        "3. 渐进提示  给方向但不给答案\n"
        "4. 连续 3 次学生回答'不知道'或低努力回答后  停止给提示  反问'具体哪里不懂'\n"
        "5. 用相似例题讲解  不直接讲解原题"
    ),
}

# 语调
_TONE_RULES: dict[str, str] = {
    "friendly": "口语化  可用鼓励性表达",
    "formal": "书面语  术语准确  避免口语",
    "encouraging": "多肯定用户的进展",
    "strict": "直接指出错误  不客套",
}


def build_system_prompt(
    user_name: str | None = None,
    temp_memory: str | None = None,
    core_memory: str | None = None,
    skills_context: str | None = None,
    prompt_ctx: PromptContext | None = None,
) -> str:
    prompt_ctx = prompt_ctx or PromptContext()
    core_memory = core_memory or "暂无核心记忆"
    temp_memory = temp_memory or "暂无临时记忆"
    skills_context = skills_context or "暂无可用 skill"

    # 风格/语调: 分组级非 None 时覆盖用户级  None 表示继承用户级
    effective_style = prompt_ctx.group_style or prompt_ctx.preferred_style
    effective_tone = prompt_ctx.group_tone or prompt_ctx.preferred_tone
    style_rule = _STYLE_RULES.get(effective_style, _STYLE_RULES["concise"])
    tone_rule = _TONE_RULES.get(effective_tone, _TONE_RULES["friendly"])
    style_section = f"""
    风格({effective_style})  {style_rule}\n
    语调({effective_tone})  {tone_rule}
    """

    # 指令合并顺序: 系统 -> 用户级 -> 分组级 -> 当前消息
    # 用 list 收集后 join 便于未来扩展更多层级
    instruction_lines: list[str] = []
    if prompt_ctx.custom_instruction.strip():
        instruction_lines.append(f"用户补充要求  {prompt_ctx.custom_instruction.strip()}")
    if prompt_ctx.group_custom_instruction.strip():
        instruction_lines.append(f"分组要求  {prompt_ctx.group_custom_instruction.strip()}")

    if instruction_lines:
        style_section += "\n" + "\n".join(instruction_lines)

    # 用户学情档案区块
    profile_section = (
        f"# 用户学情档案\n\n{prompt_ctx.user_profile_context.strip()}\n"
        if prompt_ctx.user_profile_context and prompt_ctx.user_profile_context.strip()
        else ""
    )

    return f"""
{SYSTEM_PROMPT.strip()}

> 用户昵称: {user_name}

# 输出风格

{style_section}

{profile_section}
# 核心记忆

{core_memory}

# 临时记忆

{temp_memory}

# 可用 Skills

{skills_context}
""".strip()
