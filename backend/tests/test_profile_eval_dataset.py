# backend/tests/test_profile_eval_dataset.py
"""
验证用户画像系统评测数据集 (P2-11) 的结构与覆盖度。

数据集文件: backend/tests/eval/profile_eval_dataset.jsonl

本测试不运行真实 ProfileBuilder 仅校验数据集本身:
    1. 加载 JSONL 文件 每行可解析为 JSON 对象
    2. 每条用例包含 schema 要求的字段
    3. 用例总数 >= 15
    4. 通过 description 关键词匹配 验证 10 个能力领域全部被覆盖
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

DATASET_PATH = Path(__file__).parent / "eval" / "profile_eval_dataset.jsonl"

# schema 要求的顶层字段
REQUIRED_TOP_FIELDS = {
    "case_id",
    "description",
    "user_record",
    "query",
    "expected_profile_fields",
    "expected_suppressed_fields",
    "expected_token_range",
}

# user_record 要求的子字段
REQUIRED_USER_RECORD_FIELDS = {
    "id",
    "username",
    "major",
    "grade",
    "current_week",
    "total_weeks",
    "preferred_style",
    "preferred_tone",
    "custom_instruction",
    "profile_enabled",
    "learning_profile_enabled",
    "inferred_profile_enabled",
}

# query 要求的子字段
REQUIRED_QUERY_FIELDS = {
    "current_message",
    "group_style",
    "group_tone",
    "group_custom_instruction",
}

# expected_profile_fields 要求的子字段
REQUIRED_EXPECTED_PROFILE_FIELDS = {"explicit_context", "response_preferences"}

# 10 个能力领域 -> description 中需出现的关键词 (任一 case 命中即覆盖)
CAPABILITY_KEYWORDS: dict[str, str] = {
    "显式字段派生": "显式字段",
    "响应偏好与群组覆盖": "群组覆盖",
    "群组覆盖不污染全局": "不污染全局",
    "学习状态按问题筛选": "筛选",
    "无匹配知识点": "无匹配",
    "学习画像开关关闭": "学习画像",
    "推断画像开关关闭": "推断画像",
    "suppressed字段不输出": "suppressed",
    "显式覆盖推断": "显式覆盖推断",
    "Token预算截断": "截断",
}


def _load_dataset() -> list[dict]:
    """加载 JSONL 数据集 返回用例列表。空行跳过。"""
    cases: list[dict] = []
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise AssertionError(
                    f"第 {lineno} 行 JSON 解析失败: {exc}"
                ) from exc
    return cases


def test_dataset_file_exists():
    """数据集文件存在且非空。"""
    assert DATASET_PATH.exists(), f"数据集文件不存在: {DATASET_PATH}"
    assert DATASET_PATH.stat().st_size > 0, "数据集文件为空"


def test_dataset_has_at_least_15_cases():
    """用例总数不少于 15。"""
    cases = _load_dataset()
    assert len(cases) >= 15, f"用例数不足 15 实际 {len(cases)}"


def test_each_case_has_required_top_level_fields():
    """每条用例包含 schema 要求的顶层字段。"""
    cases = _load_dataset()
    for case in cases:
        missing = REQUIRED_TOP_FIELDS - set(case.keys())
        assert not missing, (
            f"用例 {case.get('case_id', '?')} 缺少字段: {missing}"
        )


def test_each_case_has_required_user_record_fields():
    """每条用例的 user_record 包含全部要求字段。"""
    cases = _load_dataset()
    for case in cases:
        record = case["user_record"]
        missing = REQUIRED_USER_RECORD_FIELDS - set(record.keys())
        assert not missing, (
            f"用例 {case['case_id']} user_record 缺少字段: {missing}"
        )


def test_each_case_has_required_query_fields():
    """每条用例的 query 包含全部要求字段。"""
    cases = _load_dataset()
    for case in cases:
        query = case["query"]
        missing = REQUIRED_QUERY_FIELDS - set(query.keys())
        assert not missing, (
            f"用例 {case['case_id']} query 缺少字段: {missing}"
        )


def test_each_case_has_required_expected_profile_fields():
    """每条用例的 expected_profile_fields 包含 explicit_context 与 response_preferences。"""
    cases = _load_dataset()
    for case in cases:
        epf = case["expected_profile_fields"]
        missing = REQUIRED_EXPECTED_PROFILE_FIELDS - set(epf.keys())
        assert not missing, (
            f"用例 {case['case_id']} expected_profile_fields 缺少字段: {missing}"
        )
        assert isinstance(epf["explicit_context"], list), (
            f"用例 {case['case_id']} explicit_context 必须为列表"
        )
        assert isinstance(epf["response_preferences"], list), (
            f"用例 {case['case_id']} response_preferences 必须为列表"
        )


def test_each_case_has_valid_token_range():
    """每条用例的 expected_token_range 为 [min, max] 且 min <= max。"""
    cases = _load_dataset()
    for case in cases:
        token_range = case["expected_token_range"]
        assert isinstance(token_range, list), (
            f"用例 {case['case_id']} expected_token_range 必须为列表"
        )
        assert len(token_range) == 2, (
            f"用例 {case['case_id']} expected_token_range 长度必须为 2"
        )
        lo, hi = token_range
        assert isinstance(lo, int) and isinstance(hi, int), (
            f"用例 {case['case_id']} expected_token_range 元素必须为整数"
        )
        assert lo <= hi, (
            f"用例 {case['case_id']} expected_token_range min({lo}) > max({hi})"
        )


def test_each_case_has_expected_suppressed_fields_list():
    """每条用例的 expected_suppressed_fields 为列表。"""
    cases = _load_dataset()
    for case in cases:
        suppressed = case["expected_suppressed_fields"]
        assert isinstance(suppressed, list), (
            f"用例 {case['case_id']} expected_suppressed_fields 必须为列表"
        )


def test_all_10_capability_areas_covered():
    """通过 description 关键词匹配 验证 10 个能力领域全部被覆盖。"""
    cases = _load_dataset()
    descriptions = [case["description"] for case in cases]

    not_covered: list[str] = []
    for capability, keyword in CAPABILITY_KEYWORDS.items():
        if not any(keyword in desc for desc in descriptions):
            not_covered.append(f"{capability} (关键词: {keyword})")

    assert not not_covered, (
        f"以下能力领域未被任何用例 description 覆盖: {not_covered}"
    )


def test_case_ids_unique():
    """所有用例的 case_id 唯一。"""
    cases = _load_dataset()
    ids = [case["case_id"] for case in cases]
    duplicates = {cid for cid in ids if ids.count(cid) > 1}
    assert not duplicates, f"case_id 重复: {duplicates}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
