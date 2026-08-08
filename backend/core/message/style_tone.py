"""输出风格与语调规则的唯一来源。"""

from __future__ import annotations

from dataclasses import dataclass

STYLE_RULES: dict[str, str] = {
    "concise": "回答控制在 3 句内，先给结论，不铺陈背景；作业类问题优先给思路而非完整答案",
    "detailed": "完整展开，包含背景、步骤和示例；作业类问题可给完整解答，但需说明每步原理",
    "socratic": (
        "用反问引导思考，不直接给答案。先定位卡点，再逐级给提示；"
        "连续多次低努力回答时改为确认具体不懂的位置，并优先使用相似例题。"
    ),
}

TONE_RULES: dict[str, str] = {
    "friendly": "口语化，可使用适度鼓励性表达",
    "formal": "使用书面语，术语准确，避免口语",
    "encouraging": "肯定有效进展，同时准确指出问题",
    "strict": "直接指出错误，不使用无意义客套",
}

DEFAULT_STYLE = "concise"
DEFAULT_TONE = "friendly"


@dataclass(frozen=True, slots=True)
class ResolvedStyleTone:
    style: str
    tone: str
    style_rule: str
    tone_rule: str


def _clean(value: str | None) -> str:
    return value.strip() if value else ""


def resolve_style_tone(
    *,
    preferred_style: str | None,
    preferred_tone: str | None,
    group_style: str | None = None,
    group_tone: str | None = None,
) -> ResolvedStyleTone:
    """按“分组覆盖用户”的规则解析本轮最终风格与语调。"""
    preferred_style = _clean(preferred_style) or DEFAULT_STYLE
    preferred_tone = _clean(preferred_tone) or DEFAULT_TONE
    group_style = _clean(group_style)
    group_tone = _clean(group_tone)

    style = group_style or preferred_style
    tone = group_tone or preferred_tone

    # 未知值回退到默认规则，但保留最终展示名，便于排查非法配置。
    style_rule = STYLE_RULES.get(style, STYLE_RULES[DEFAULT_STYLE])
    tone_rule = TONE_RULES.get(tone, TONE_RULES[DEFAULT_TONE])

    return ResolvedStyleTone(
        style=style,
        tone=tone,
        style_rule=style_rule,
        tone_rule=tone_rule,
    )
