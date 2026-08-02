# backend/core/agent/utils.py

import json
import re

from backend.core.utils.models import ParsedOutput, ToolCall


def _try_cast(value: str):
    """将工具参数按 JSON 类型解析，无法解析时保留原字符串。"""
    value = value.strip()

    if not value:
        return ""

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def parse_output(raw_text: str) -> ParsedOutput:
    result = ParsedOutput()

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
        args = {k: _try_cast(v) for k, v in param_matches}

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

    def __init__(self) -> None:
        self.phase = "reasoning"
        self.pending = ""
        self.raw_parts: list[str] = []
        self.opening_tag_handled = False

    @property
    def raw_text(self) -> str:
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

        if self.phase == "content" and self.pending:
            events.append(("content", self.pending))
            self.pending = ""

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
        elif self.phase == "content" and self.pending:
            events.append(("content", self.pending))
            self.pending = ""

        return events

    def _parse_reasoning(self, events: list[tuple[str, str]]) -> None:
        if not self.opening_tag_handled:
            stripped = self.pending.lstrip()

            # 有些调用的生成提示已经包含 <think>，有些则由模型输出。
            if self.THINK_OPEN.startswith(stripped) and stripped != self.THINK_OPEN:
                return

            if stripped.startswith(self.THINK_OPEN):
                leading_length = len(self.pending) - len(stripped)
                self.pending = (
                    self.pending[:leading_length]
                    + stripped.removeprefix(self.THINK_OPEN)
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

    @staticmethod
    def _partial_suffix_length(value: str, marker: str) -> int:
        max_length = min(len(value), len(marker) - 1)
        for length in range(max_length, 0, -1):
            if value.endswith(marker[:length]):
                return length
        return 0


def main() -> None:
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
