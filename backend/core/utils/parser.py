# backend/core/utils/parser.py

"""提供 `parser` 相关功能。"""

import json
import re

from backend.core.utils.models import ParsedOutput, ToolCall
from backend.core.utils.tool_arguments import (
    declared_schema_type,
    normalize_tool_arguments,
    schemas_by_name,
)


def _try_cast(value: str):
    """将工具参数按 JSON 类型解析，无法解析时保留原字符串。"""
    value = value.strip()

    if not value:
        return ""

    # DeepSeek 系列偶尔会按 Python 字面量输出 True/False/None，
    # 而不是 JSON 的 true/false/null。工具参数协议在这里统一归一化。
    aliases = {"true": True, "false": False, "none": None, "null": None}
    normalized = value.casefold()
    if normalized in aliases:
        return aliases[normalized]

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def parse_output(
    raw_text: str,
    tool_schemas: list[dict] | tuple[dict, ...] | None = None,
) -> ParsedOutput:
    """解析 `output` 相关数据。

    Args:
        raw_text: str => `raw_text` 参数。
        tool_schemas: list[dict] | tuple[dict, ...] | None => `tool_schemas` 参数。

    Returns:
        ParsedOutput => 处理结果。
    """
    result = ParsedOutput()
    schema_lookup = schemas_by_name(tool_schemas)

    # 提取 reasoning
    think_match = re.search(r"(?:<think>)?(.*?)</think>", raw_text, re.DOTALL)
    if think_match:
        result.reasoning = think_match.group(1).strip()

    # 提取所有 <tool_call>...</tool_call> 块
    tool_call_blocks = re.findall(r"<tool_call>(.*?)</tool_call>", raw_text, re.DOTALL)

    if not tool_call_blocks:
        # 没有 tool_call,说明是纯文本回答,取 </think> 之后的内容作为 content
        remaining = re.sub(r"(?:<think>)?.*?</think>", "", raw_text, flags=re.DOTALL)
        result.content = remaining.strip() or raw_text.strip()
        return result

    for block in tool_call_blocks:
        # 提取 function 名字
        func_match = re.search(r"<function=([^>\s]+)>", block)
        if not func_match:
            continue
        func_name = func_match.group(1)

        # 提取所有 parameter
        param_matches = re.findall(
            r"<parameter=([^>\s]+)>\s*(.*?)\s*</parameter>",
            block,
            re.DOTALL,
        )
        schema = schema_lookup.get(func_name)
        properties = (
            schema.get("function", {})
            .get("parameters", {})
            .get("properties", {})
            if schema is not None
            else {}
        )
        args = {
            key: (
                raw_value.strip()
                if declared_schema_type(properties.get(key, {})) == "string"
                else _try_cast(raw_value)
            )
            for key, raw_value in param_matches
        }
        if schema is not None:
            try:
                args = normalize_tool_arguments(schema, args)
            except ValueError:
                # 解析层只负责尽可能恢复 Schema 类型。非法值交给
                # ToolRegistry 的执行边界处理，避免一次坏参数把整轮请求变成 500。
                pass

        result.tool_calls.append(ToolCall(name=func_name, arguments=args))

    return result


class StreamOutputParser:
    """增量解析 Qwen 的 reasoning、正文和工具调用边界。

    `feed()` 可接收任意大小的模型增量，包括被拆开的 XML 标签。
    工具调用原文只保留在 `raw_text` 中，不作为可见文本事件返回。
    """

    THINK_OPEN = "<think>"
    THINK_CLOSE = "</think>"
    TOOL_OPEN = "<tool_call>"
    # 有些模型会先输出一段可见说明，再输出工具调用。工具协议无论出现在
    # `</think>` 后的哪个位置，都不能作为正文 SSE 事件发送给前端。
    CONTENT_STOP_TOKENS: tuple[str, ...] = (TOOL_OPEN,)

    def __init__(self) -> None:
        """初始化 `StreamOutputParser` 实例。"""
        self.phase = "reasoning"
        self.pending = ""
        self.raw_parts: list[str] = []
        self.opening_tag_handled = False

    @property
    def raw_text(self) -> str:
        """处理 `raw_text` 相关逻辑。"""
        return "".join(self.raw_parts)

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        """输入一个增量，返回当前可安全展示的事件。"""
        if not chunk:
            return []

        self.raw_parts.append(chunk)
        self.pending += chunk
        events: list[tuple[str, str]] = []

        if self.phase == "reasoning":
            self._parse_reasoning(events)

        if self.phase == "undecided":
            self._determine_output_type()

        if self.phase == "content":
            self._flush_content(events)

        return events

    def finish(self) -> list[tuple[str, str]]:
        """模型流结束后刷新尚未发出的安全文本。"""
        events: list[tuple[str, str]] = []

        if self.phase == "reasoning" and self.pending:
            events.append(("reasoning", self.pending))
            self.pending = ""
        elif self.phase == "undecided":
            self._determine_output_type(final=True)
            if self.phase == "content" and self.pending:
                events.append(("content", self.pending))
                self.pending = ""
        elif self.phase == "content":
            self._flush_content(events, final=True)

        return events

    def _parse_reasoning(self, events: list[tuple[str, str]]) -> None:
        """解析 `reasoning` 相关数据。"""
        if not self.opening_tag_handled:
            stripped = self.pending.lstrip()

            # 有些调用的生成提示已经包含 <think>，有些则由模型输出。
            if self.THINK_OPEN.startswith(stripped) and stripped != self.THINK_OPEN:
                return

            if stripped.startswith(self.THINK_OPEN):
                leading_length = len(self.pending) - len(stripped)
                self.pending = self.pending[:leading_length] + stripped.removeprefix(
                    self.THINK_OPEN
                )

            self.opening_tag_handled = True

        if self.THINK_CLOSE in self.pending:
            reasoning, self.pending = self.pending.split(
                self.THINK_CLOSE,
                maxsplit=1,
            )
            if reasoning:
                events.append(("reasoning", reasoning))
            self.phase = "undecided"
            return

        # 保留可能属于跨 chunk 结束标签的最短后缀。
        keep_length = self._partial_suffix_length(self.pending, self.THINK_CLOSE)
        emit_length = len(self.pending) - keep_length
        if emit_length <= 0:
            return

        reasoning = self.pending[:emit_length]
        self.pending = self.pending[emit_length:]
        if reasoning:
            events.append(("reasoning", reasoning))

    def _determine_output_type(self, final: bool = False) -> None:
        """处理 `_determine_output_type` 相关逻辑。"""
        candidate = self.pending.lstrip()
        if not candidate:
            return

        if self.TOOL_OPEN.startswith(candidate):
            if candidate == self.TOOL_OPEN or final:
                self.phase = "tool"
            return

        if candidate.startswith(self.TOOL_OPEN):
            self.phase = "tool"
            return

        self.phase = "content"

    def _flush_content(
        self,
        events: list[tuple[str, str]],
        final: bool = False,
    ) -> None:
        """发送正文，同时避免把跨 chunk 的结束 token 暴露给前端。"""
        if not self.pending or self.phase != "content":
            return

        stop_positions = [
            self.pending.find(token)
            for token in self.CONTENT_STOP_TOKENS
            if token in self.pending
        ]
        if stop_positions:
            stop_position = min(stop_positions)
            content = self.pending[:stop_position]
            self.pending = ""
            self.phase = "finished"
            if content:
                events.append(("content", content))
            return

        if final or not self.CONTENT_STOP_TOKENS:
            content = self.pending
            self.pending = ""
            if content:
                events.append(("content", content))
            return

        keep_length = max(
            self._partial_suffix_length(self.pending, token)
            for token in self.CONTENT_STOP_TOKENS
        )
        emit_length = len(self.pending) - keep_length
        if emit_length <= 0:
            return

        content = self.pending[:emit_length]
        self.pending = self.pending[emit_length:]
        events.append(("content", content))

    @staticmethod
    def _partial_suffix_length(value: str, marker: str) -> int:
        """处理 `_partial_suffix_length` 相关逻辑。"""
        max_length = min(len(value), len(marker) - 1)
        for length in range(max_length, 0, -1):
            if value.endswith(marker[:length]):
                return length
        return 0


def main() -> None:
    """运行当前模块的命令行入口。"""
    OUTPUT = """
    用户问了两个问题：
    1. 北京天气怎么样 - 我需要使用 get_weather 工具，参数是 city="北京"
    2. 计算2和3的和 - 我需要使用 add_two_nums 工具，参数是 num1=2, num2=3

    这两个请求都是独立的，我可以同时调用这两个工具。
    </think>

    <tool_call>
    <function=get_weather>
    <parameter=city>
    北京
    </parameter>
    </function>
    </tool_call>
    <tool_call>
    <function=add_two_nums>
    <parameter=num1>
    2
    </parameter>
    <parameter=num2>
    3
    </parameter>
    </function>
    </tool_call>
    """

    print(parse_output(OUTPUT))


if __name__ == "__main__":
    main()
