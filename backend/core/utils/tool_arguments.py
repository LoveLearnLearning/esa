"""Tool argument normalization shared by protocol parsing and execution."""

from __future__ import annotations

import json
from typing import Any


def declared_schema_type(specification: dict[str, Any]) -> str | None:
    """返回 Schema 声明的非 null 主类型。"""
    declared = specification.get("type")
    if isinstance(declared, str):
        return declared
    if isinstance(declared, list):
        return next(
            (
                item
                for item in declared
                if isinstance(item, str) and item != "null"
            ),
            None,
        )
    return None


def _normalize_boolean(key: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        candidate = value.strip().casefold()
        if candidate in {"true", "1"}:
            return True
        if candidate in {"false", "0"}:
            return False
    raise ValueError(f"参数 {key!r} 必须是布尔值")


def _normalize_integer(key: str, value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"参数 {key!r} 必须是整数")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise ValueError(f"参数 {key!r} 必须是整数")
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as exc:
            raise ValueError(f"参数 {key!r} 必须是整数") from exc
    raise ValueError(f"参数 {key!r} 必须是整数")


def _normalize_number(key: str, value: Any) -> int | float:
    if isinstance(value, bool):
        raise ValueError(f"参数 {key!r} 必须是数值")
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValueError(f"参数 {key!r} 必须是数值") from exc
        if isinstance(parsed, bool) or not isinstance(parsed, (int, float)):
            raise ValueError(f"参数 {key!r} 必须是数值")
        return parsed
    raise ValueError(f"参数 {key!r} 必须是数值")


def _normalize_container(
    key: str,
    value: Any,
    expected_type: type,
    type_name: str,
) -> Any:
    if isinstance(value, expected_type):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"参数 {key!r} 必须是{type_name}") from exc
        if isinstance(parsed, expected_type):
            return parsed
    raise ValueError(f"参数 {key!r} 必须是{type_name}")


def normalize_tool_arguments(
    schema: dict[str, Any],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """按目标工具 JSON Schema 恢复参数类型。

    XML 参数本质上是文本，不能仅凭 ``"0"`` 判断它应当是
    字符串还是整数。这里以工具自己声明的 Schema 作为唯一类型依据。
    ``None`` 保持不变，以兼容现有可选参数的工具签名。
    """
    properties = (
        schema.get("function", {}).get("parameters", {}).get("properties", {})
    )
    normalized = dict(arguments)

    for key, value in arguments.items():
        specification = properties.get(key)
        if not isinstance(specification, dict) or value is None:
            continue

        declared_type = declared_schema_type(specification)
        if declared_type == "string":
            if isinstance(value, str):
                converted = value
            elif isinstance(value, (int, float, bool)):
                converted = json.dumps(value, ensure_ascii=False)
            else:
                raise ValueError(f"参数 {key!r} 必须是字符串")
        elif declared_type == "boolean":
            converted = _normalize_boolean(key, value)
        elif declared_type == "integer":
            converted = _normalize_integer(key, value)
        elif declared_type == "number":
            converted = _normalize_number(key, value)
        elif declared_type == "array":
            converted = _normalize_container(key, value, list, "数组")
        elif declared_type == "object":
            converted = _normalize_container(key, value, dict, "对象")
        else:
            converted = value

        allowed_values = specification.get("enum")
        if isinstance(allowed_values, list) and converted not in allowed_values:
            raise ValueError(
                f"参数 {key!r} 必须是 {allowed_values!r} 之一"
            )
        normalized[key] = converted

    return normalized


def schemas_by_name(
    schemas: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> dict[str, dict[str, Any]]:
    if not schemas:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for schema in schemas:
        name = schema.get("function", {}).get("name")
        if isinstance(name, str) and name:
            result[name] = schema
    return result
