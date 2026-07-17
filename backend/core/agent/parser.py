# backend/core/agent/utils.py

import re
from dataclasses import dataclass, field

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


@dataclass
class ToolCall:
    name: str
    arguments: dict


@dataclass
class ParsedOutput:
    reasoning: str | None = None
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


def _try_cast(value: str):
    """参数值尝试转成 int/float/bool,转不了就保留字符串"""
    value = value.strip()
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def parse_output(raw_text: str) -> ParsedOutput:
    result = ParsedOutput()

    # 1. 提取 reasoning(<think>...</think>,注意你的样本里开头标签可能被截掉了,做兼容)
    think_match = re.search(r"(?:<think>)?(.*?)</think>", raw_text, re.DOTALL)
    if think_match:
        result.reasoning = think_match.group(1).strip()

    # 2. 提取所有 <tool_call>...</tool_call> 块
    tool_call_blocks = re.findall(r"<tool_call>(.*?)</tool_call>", raw_text, re.DOTALL)

    if not tool_call_blocks:
        # 没有 tool_call,说明是纯文本回答,取 </think> 之后的内容作为 content
        remaining = re.sub(r"(?:<think>)?.*?</think>", "", raw_text, flags=re.DOTALL)
        result.content = remaining.strip() or raw_text.strip()
        return result

    for block in tool_call_blocks:
        # 提取 function 名字
        func_match = re.search(r"<function=(\w+)>", block)
        if not func_match:
            continue
        func_name = func_match.group(1)

        # 提取所有 parameter
        param_matches = re.findall(
            r"<parameter=(\w+)>\s*(.*?)\s*</parameter>", block, re.DOTALL
        )
        args = {k: _try_cast(v) for k, v in param_matches}

        result.tool_calls.append(ToolCall(name=func_name, arguments=args))

    return result


def main() -> None:
    print(parse_output(OUTPUT))


if __name__ == "__main__":
    main()
