# backend/agent/mm/tests/test_providers.py

"""验证 `providers` 相关行为与回归场景。"""

from __future__ import annotations

import pytest

from backend.agent.mm.providers import _parse_visual_analysis


@pytest.mark.parametrize(
    "content",
    [
        '{"description":"课表","visible_text":"周一","content_type":"table"}',
        '```json\n{"description":"课表","visible_text":"周一","content_type":"table"}\n```',
        '<think>先分析布局</think>\n{"description":"课表","visible_text":"周一","content_type":"table"}',
        '分析结果如下：\n{"description":"课表","visible_text":"周一","content_type":"table"}\n以上。',
    ],
)
def test_parse_visual_analysis_accepts_wrapped_json(content: str) -> None:
    """验证 `parse_visual_analysis_accepts_wrapped_json` 场景。"""
    result = _parse_visual_analysis(content)

    assert result.description == "课表"
    assert result.visible_text == "周一"
    assert result.content_type == "table"


def test_parse_visual_analysis_skips_unrelated_json_object() -> None:
    """验证 `parse_visual_analysis_skips_unrelated_json_object` 场景。"""
    result = _parse_visual_analysis(
        '{"status":"thinking"}\n'
        '{"description":"课表","visible_text":"周一","content_type":"table"}'
    )

    assert result.description == "课表"


@pytest.mark.parametrize("content", ["没有 JSON", "[]", '{"description":""}'])
def test_parse_visual_analysis_rejects_invalid_content(content: str) -> None:
    """验证 `parse_visual_analysis_rejects_invalid_content` 场景。"""
    with pytest.raises(ValueError):
        _parse_visual_analysis(content)
