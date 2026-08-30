"""Safe, structured error projections for all Agent tool executions."""

from __future__ import annotations

import asyncio
import traceback
from typing import Any, Mapping

from backend.core.utils.models import ToolExecutionResult


ERROR_MESSAGES: dict[str, str] = {
    "timeout": "工具执行超时",
    "rate_limited": "工具服务请求过于频繁，请稍后重试",
    "upstream_unavailable": "上游工具服务暂时不可用",
    "network_error": "工具网络连接暂时不可用",
    "temporary_tool_error": "工具暂时无法完成请求",
    "tool_not_available": "当前上下文无法使用该工具",
    "invalid_tool_arguments": "工具参数无效",
    "resource_capability_required": "当前请求缺少工具所需的资源授权",
    "attachment_not_authorized": "请求的附件不在当前对话授权范围内",
    "permission_denied": "当前请求无权执行该工具",
    "memory_policy_denied": "当前记忆策略不允许执行该工具",
    "non_idempotent_action_rejected": "写操作无法安全自动重试",
    "tool_internal_error": "工具暂时无法完成请求，请稍后重试",
    "tool_budget_exhausted": "本轮工具调用预算已用完",
    "duplicate_call_blocked": "相同的失败工具调用已达到重复上限",
    "wall_time_exhausted": "本轮 Agent 运行时间已用完",
}

RETRYABLE_ERROR_CODES = frozenset(
    {
        "timeout",
        "rate_limited",
        "upstream_unavailable",
        "network_error",
        "temporary_tool_error",
    }
)


def structured_tool_error(
    error_code: str,
    *,
    tool: str,
    attempt: int = 1,
    retryable: bool | None = None,
    message: str | None = None,
    retry_after_ms: int | None = None,
    request_id: str | None = None,
    run_id: str | None = None,
    elapsed_ms: float | None = None,
    exception: BaseException | None = None,
    audit_metadata: Mapping[str, Any] | None = None,
) -> ToolExecutionResult:
    """Build model/display-safe content and a detailed private audit channel."""

    is_retryable = (
        error_code in RETRYABLE_ERROR_CODES
        if retryable is None
        else retryable
    )
    safe_message = message or ERROR_MESSAGES.get(
        error_code, ERROR_MESSAGES["tool_internal_error"]
    )
    model_content: dict[str, Any] = {
        "ok": False,
        "error_code": error_code,
        # Compatibility alias for existing model/tool protocol consumers.
        "error": error_code,
        "retryable": is_retryable,
        "tool": tool,
        "attempt": attempt,
        "message": safe_message,
    }
    if retry_after_ms is not None:
        model_content["retry_after_ms"] = max(0, int(retry_after_ms))

    display_content = dict(model_content)
    audit = dict(audit_metadata or {})
    audit.update(
        {
            "error_code": error_code,
            "tool": tool,
            "attempt": attempt,
            "request_id": request_id,
            "run_id": run_id,
            "elapsed_ms": elapsed_ms,
        }
    )
    if exception is not None:
        audit.update(
            {
                "exception_type": type(exception).__name__,
                "exception_message": str(exception),
                "traceback": "".join(
                    traceback.format_exception(
                        type(exception), exception, exception.__traceback__
                    )
                ),
            }
        )
    return ToolExecutionResult(model_content, display_content, audit)


def classify_tool_exception(error: BaseException) -> tuple[str, bool, int | None]:
    """Classify known transient failures without importing optional SDKs."""

    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return "timeout", True, 1000
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
    retry_after_ms = _retry_after_ms(error)
    name = type(error).__name__.lower()
    if status_code == 429 or "ratelimit" in name or "rate_limit" in name:
        return "rate_limited", True, retry_after_ms or 1000
    if status_code in {502, 503, 504} or "serviceunavailable" in name:
        return "upstream_unavailable", True, retry_after_ms or 1000
    if isinstance(error, ConnectionError) or any(
        marker in name
        for marker in (
            "networkerror",
            "connecterror",
            "connectionerror",
            "transporterror",
            "requesterror",
            "protocolerror",
        )
    ):
        return "network_error", True, retry_after_ms or 1000
    if isinstance(error, RuntimeError):
        return "temporary_tool_error", True, retry_after_ms or 1000
    if isinstance(error, (TypeError, ValueError)):
        return "invalid_tool_arguments", False, None
    return "tool_internal_error", False, None


def normalize_tool_error_result(
    result: object,
    *,
    tool: str,
    attempt: int,
    request_id: str | None = None,
    run_id: str | None = None,
    elapsed_ms: float | None = None,
) -> object:
    """Upgrade legacy error mappings while retaining existing success payloads."""

    if isinstance(result, str) and (
        result.strip().lower().startswith("[error]")
        or result.strip().lower().endswith("skill not found!")
    ):
        error_code = (
            "invalid_tool_arguments"
            if result.strip().lower().endswith("skill not found!")
            else "tool_internal_error"
        )
        return structured_tool_error(
            error_code,
            tool=tool,
            attempt=attempt,
            retryable=False,
            request_id=request_id,
            run_id=run_id,
            elapsed_ms=elapsed_ms,
            audit_metadata={"legacy_detail": result},
        )
    if isinstance(result, ToolExecutionResult):
        model_content = result.model_content
        if not _is_error_mapping(model_content):
            return result
        source = model_content
        existing_audit = result.audit_metadata
    elif _is_error_mapping(result):
        source = result
        existing_audit = None
    else:
        return result

    assert isinstance(source, Mapping)
    error_code = str(
        source.get("error_code") or source.get("error") or "tool_internal_error"
    )
    retryable = source.get("retryable")
    retry_after_ms = source.get("retry_after_ms")
    audit = dict(existing_audit) if isinstance(existing_audit, Mapping) else {}
    for key in (
        "detail",
        "required",
        "loaded_skill",
        "requested_skill",
        "requested_attachment_id",
        "authorized_attachment_ids",
    ):
        if key in source:
            audit[f"legacy_{key}"] = source[key]
    return structured_tool_error(
        error_code,
        tool=tool,
        attempt=attempt,
        retryable=(
            bool(retryable)
            if isinstance(retryable, bool)
            else error_code in RETRYABLE_ERROR_CODES
        ),
        message=(
            str(source["message"])
            if isinstance(source.get("message"), str)
            else None
        ),
        retry_after_ms=(
            int(retry_after_ms)
            if isinstance(retry_after_ms, (int, float))
            else None
        ),
        request_id=request_id,
        run_id=run_id,
        elapsed_ms=elapsed_ms,
        audit_metadata=audit,
    )


def tool_error_payload(result: object) -> Mapping[str, Any] | None:
    """Return the model-facing structured error payload, when present."""

    model_content = (
        result.model_content if isinstance(result, ToolExecutionResult) else result
    )
    return model_content if _is_error_mapping(model_content) else None


def _is_error_mapping(value: object) -> bool:
    return isinstance(value, Mapping) and (
        value.get("ok") is False
        or isinstance(value.get("error_code"), str)
        or isinstance(value.get("error"), str)
    )


def _retry_after_ms(error: BaseException) -> int | None:
    value = getattr(error, "retry_after", None)
    if value is None:
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None)
        if isinstance(headers, Mapping):
            value = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return max(0, int(float(value) * 1000))
    except (TypeError, ValueError):
        return None
