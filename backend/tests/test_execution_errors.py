"""回归测试：工具错误协议的归一化边界。"""

from __future__ import annotations

from backend.agent.tools.execution_errors import (
    normalize_tool_error_result,
    structured_tool_error,
)
from backend.core.utils.models import ToolExecutionResult


def test_calculator_business_error_keeps_diagnostic_and_context() -> None:
    result = normalize_tool_error_result(
        {
            "expression": "1024/(10-10)",
            "result": None,
            "error": "除零错误",
        },
        tool="calculator",
        attempt=1,
    )

    assert isinstance(result, ToolExecutionResult)
    assert result.model_content == {
        "ok": False,
        "error_code": "invalid_tool_arguments",
        "error": "invalid_tool_arguments",
        "retryable": False,
        "tool": "calculator",
        "attempt": 1,
        "message": "除零错误",
    }
    assert result.audit_metadata["legacy_error"] == "除零错误"
    assert result.audit_metadata["legacy_expression"] == "1024/(10-10)"
    assert result.audit_metadata["legacy_result"] is None


def test_wrapped_calculator_business_error_keeps_context_in_audit() -> None:
    wrapped = ToolExecutionResult(
        {
            "expression": "1/0",
            "result": None,
            "error": "除零错误",
        },
        {"expression": "1/0", "result": None, "error": "除零错误"},
    )

    result = normalize_tool_error_result(wrapped, tool="calculator", attempt=1)

    assert isinstance(result, ToolExecutionResult)
    assert result.audit_metadata["legacy_expression"] == "1/0"
    assert result.audit_metadata["legacy_result"] is None
    assert result.model_content["message"] == "除零错误"


def test_unknown_error_code_is_not_exposed_as_protocol_code() -> None:
    result = normalize_tool_error_result(
        {"ok": False, "error_code": "backend_secret", "detail": "internal"},
        tool="web_search",
        attempt=2,
    )

    assert isinstance(result, ToolExecutionResult)
    assert result.model_content["error_code"] == "tool_internal_error"
    assert result.model_content["error"] == "tool_internal_error"
    assert result.audit_metadata["legacy_error_code"] == "backend_secret"
    assert result.audit_metadata["legacy_detail"] == "internal"


def test_legacy_parameter_error_is_classified_as_invalid_arguments() -> None:
    result = normalize_tool_error_result(
        "[Error]: similarity_threshold must be between 0 and 1",
        tool="retrieve_knowledge",
        attempt=1,
    )

    assert isinstance(result, ToolExecutionResult)
    assert result.model_content["error_code"] == "invalid_tool_arguments"
    assert result.model_content["message"] == "工具参数无效"
    assert result.audit_metadata["legacy_detail"] == (
        "[Error]: similarity_threshold must be between 0 and 1"
    )


def test_existing_structured_error_remains_unchanged() -> None:
    result = structured_tool_error("timeout", tool="web_search", attempt=2)
    normalized = normalize_tool_error_result(
        result,
        tool="web_search",
        attempt=2,
    )

    assert normalized is not result
    assert isinstance(normalized, ToolExecutionResult)
    assert normalized.model_content == result.model_content
    assert normalized.audit_metadata["error_code"] == "timeout"
