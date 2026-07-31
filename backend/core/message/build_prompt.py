# backend/core/message/build_prompt.py

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
当某个 skill 的描述与用户任务匹配时  先调用 load_skill 加载完整说明
加载 skill 后按照其中的步骤完成任务
不要调用与当前任务无关的 skill
不要编造不存在的 skill
"""

# 风格
_STYLE_RULES: dict[str, str] = {
    "concise": "回答控制在 3 句内  先给结论  不铺陈背景",
    "detailed": "完整展开  含背景  步骤  示例",
    "socratic": "用反问引导用户思考  不直接给答案",
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
    preferred_style: str = "concise",
    preferred_tone: str = "friendly",
    custom_instruction: str = "",
    user_profile_context: str | None = None,
) -> str:
    core_memory = core_memory or "暂无核心记忆"
    temp_memory = temp_memory or "暂无临时记忆"
    skills_context = skills_context or "暂无可用 skill"

    # 风格
    style_rule = _STYLE_RULES.get(preferred_style, _STYLE_RULES["concise"])
    tone_rule = _TONE_RULES.get(preferred_tone, _TONE_RULES["friendly"])
    style_section = f"""
    风格({preferred_style})  {style_rule}\n
    语调({preferred_tone})  {tone_rule}
    """

    # 自定义指令
    if custom_instruction.strip():
        style_section += f"\n用户补充要求  {custom_instruction.strip()}"

    # 用户学情档案区块
    profile_section = (
        f"# 用户学情档案\n\n{user_profile_context.strip()}\n"
        if user_profile_context and user_profile_context.strip()
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