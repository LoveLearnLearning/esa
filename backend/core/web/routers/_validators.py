# backend/core/web/routers/_validators.py

from fastapi import HTTPException, status

from backend.core.web.schemas import VALID_STYLES, VALID_TONES


def validate_style_tone(
    style: str | None,
    tone: str | None,
) -> None:
    """校验 style / tone 枚举值 None 表示继承用户级 跳过校验 非法值抛 400

    Args:
        style: str | None => 风格值 None 表示继承用户级 不校验
        tone: str | None  => 语调值 None 表示继承用户级 不校验
    """
    if style is not None and style not in VALID_STYLES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"style 非法 合法值: {sorted(VALID_STYLES)}",
        )
    if tone is not None and tone not in VALID_TONES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"tone 非法 合法值: {sorted(VALID_TONES)}",
        )
