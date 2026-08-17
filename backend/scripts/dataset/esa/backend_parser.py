# backend/scripts/dataset/esa/backend_parser.py

"""后端 parse_output 的离线复刻，供评测和兼容性测试共用。

`parse_output_current` 逐字复刻 backend/core/utils/parser.py + core/utils/tool_arguments.py，
同时支持 Qwen 原生 JSON 和现有 XML。`parse_output_dual` 保留为兼容别名。

为什么这里允许复刻（其它地方一律"能跑就别想"）
------------------------------------------------
评测器要在没有后端源码的环境里跑（超算、别人 clone 下来的数据集仓库），
所以解析器只能是本地一份复刻。代价是它会悄悄和后端脱节 ——
2026-08-11 就发生了一次：后端加了"按 schema 恢复参数类型"，这里还是旧版。

所以配了一道机器检查把它钉住：
    dataset/tools/capture_parser_golden.py   拿真实后端 parse_output 跑一批输入，存结果
    dataset/tests/test_parser_compat.py      断言这里的实现逐字复现那批结果
指纹对不上就说明后端改了解析器，重抓黄金样例、按差异改这个文件。

2026-08-11 同步的改动（`parser.py:79-99`、`tool_arguments.py:88-137`）
--------------------------------------------------------------------
XML 参数本质是文本，`"0"` 到底是字符串还是整数只能问 schema。后端现在：

1. 抽参数时先看声明类型：声明 `string` 的直接取原文，其余走 `_try_cast`
   —— 所以 string 参数的 `"0"` 不再被 `json.loads` 变成整数 0。
2. 再用 `normalize_tool_arguments` 按 schema 把类型掰回去，并校验 enum。
3. 掰不动就 `except ValueError: pass` 原样保留，交给执行边界报错
   —— 一次坏参数不该把整轮请求变成 500。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """封装 `ToolCall` 的状态与行为。"""
    name: str
    arguments: dict


@dataclass
class ParsedOutput:
    """表示 `parsed output` 数据结构。"""
    reasoning: str = ""
    content: str = ""
    tool_calls: list = field(default_factory=list)


def _try_cast(value: str):
    """复刻后端 _try_cast：含 DeepSeek 系 Python 字面量的归一化。"""
    value = value.strip()
    if not value:
        return ""
    aliases = {"true": True, "false": False, "none": None, "null": None}
    if value.casefold() in aliases:
        return aliases[value.casefold()]
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


# --------------------------------------------------------------------------
# 以下逐条复刻 backend/core/utils/tool_arguments.py
# --------------------------------------------------------------------------


def declared_schema_type(specification: dict[str, Any]) -> str | None:
    """schema 声明的非 null 主类型。`["string","null"]` 这种取 string。"""
    declared = specification.get("type")
    if isinstance(declared, str):
        return declared
    if isinstance(declared, list):
        return next((i for i in declared if isinstance(i, str) and i != "null"), None)
    return None


def _normalize_boolean(key: str, value):
    """规范化 `boolean` 相关数据。"""
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


def _normalize_integer(key: str, value):
    """规范化 `integer` 相关数据。"""
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


def _normalize_number(key: str, value):
    """规范化 `number` 相关数据。"""
    if isinstance(value, bool):
        raise ValueError(f"参数 {key!r} 必须是数值")
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value.strip())
        except json.JSONDecodeError as exc:
            raise ValueError(f"参数 {key!r} 必须是数值") from exc
        if isinstance(parsed, bool) or not isinstance(parsed, (int, float)):
            raise ValueError(f"参数 {key!r} 必须是数值")
        return parsed
    raise ValueError(f"参数 {key!r} 必须是数值")


def _normalize_container(key: str, value, expected_type: type, type_name: str):
    """规范化 `container` 相关数据。"""
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


def normalize_tool_arguments(schema: dict, arguments: dict) -> dict:
    """按目标工具的 JSON Schema 恢复参数类型，并校验 enum。

    `None` 保持不变（兼容可选参数）。任何一个参数掰不动就整体抛 ValueError，
    调用方负责决定是原样保留还是报错 —— 后端选的是原样保留。
    """
    properties = schema.get("function", {}).get("parameters", {}).get("properties", {})
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
            raise ValueError(f"参数 {key!r} 必须是 {allowed_values!r} 之一")
        normalized[key] = converted

    return normalized


def schemas_by_name(schemas) -> dict[str, dict]:
    """处理 `schemas_by_name` 相关逻辑。"""
    if not schemas:
        return {}
    out: dict[str, dict] = {}
    for schema in schemas:
        name = schema.get("function", {}).get("name")
        if isinstance(name, str) and name:
            out[name] = schema
    return out


# --------------------------------------------------------------------------
# 两个解析器
# --------------------------------------------------------------------------


def _xml_arguments(block: str, schema: dict | None) -> dict:
    """抽 <parameter=K>v</parameter> 并按 schema 恢复类型（parser.py:70-99）。"""
    param_matches = re.findall(r"<parameter=([^>\s]+)>\s*(.*?)\s*</parameter>", block, re.DOTALL)
    properties = (
        schema.get("function", {}).get("parameters", {}).get("properties", {})
        if schema is not None else {}
    )
    args = {
        key: (raw.strip() if declared_schema_type(properties.get(key, {})) == "string"
              else _try_cast(raw))
        for key, raw in param_matches
    }
    if schema is not None:
        try:
            args = normalize_tool_arguments(schema, args)
        except ValueError:
            # 后端在这里刻意吞掉：解析层只负责尽力恢复类型，
            # 非法值交给 ToolRegistry 的执行边界，别让一次坏参数变成 500。
            pass
    return args


def parse_output_current(raw_text: str, tool_schemas=None) -> ParsedOutput:
    """复刻生产解析器：先试 Qwen JSON，再回退现有 XML。"""
    result = ParsedOutput()
    lookup = schemas_by_name(tool_schemas)

    m = re.search(r"(?:<think>)?(.*?)</think>", raw_text, re.DOTALL)
    if m:
        result.reasoning = m.group(1).strip()

    blocks = re.findall(r"<tool_call>(.*?)</tool_call>", raw_text, re.DOTALL)
    if not blocks:
        remaining = re.sub(r"(?:<think>)?.*?</think>", "", raw_text, flags=re.DOTALL)
        result.content = remaining.strip() or raw_text.strip()
        return result

    for block in blocks:
        try:
            payload = json.loads(block.strip())
        except json.JSONDecodeError:
            payload = None

        json_calls = payload if isinstance(payload, list) else [payload]
        parsed_json_call = False
        for call in json_calls:
            if not isinstance(call, dict) or not isinstance(call.get("name"), str):
                continue
            arguments = call.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    continue
            if not isinstance(arguments, dict):
                continue

            name = call["name"]
            schema = lookup.get(name)
            if schema is not None:
                try:
                    arguments = normalize_tool_arguments(schema, arguments)
                except ValueError:
                    pass
            result.tool_calls.append(ToolCall(name=name, arguments=arguments))
            parsed_json_call = True

        if parsed_json_call:
            continue

        fm = re.search(r"<function=([^>\s]+)>", block)
        if not fm:
            continue
        name = fm.group(1)
        result.tool_calls.append(
            ToolCall(name=name, arguments=_xml_arguments(block, lookup.get(name)))
        )
    return result


def parse_output_dual(raw_text: str, tool_schemas=None) -> ParsedOutput:
    """兼容旧评测配置的别名。"""
    return parse_output_current(raw_text, tool_schemas)


PARSERS = {"current": parse_output_current, "dual": parse_output_dual}
