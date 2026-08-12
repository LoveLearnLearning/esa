"""给 LLaMA-Factory 加一个 `tool_format="esa_xml"`，产出 ESA 后端 `parse_output` 认的 XML。

为什么需要它（P0-1）
--------------------
后端 `backend/core/utils/parser.py:parse_output` **只认**这种形状：

    <tool_call>
    <function=get_mastery_report>
    <parameter=course>
    数据结构
    </parameter>
    </function>
    </tool_call>

而 LLaMA-Factory 0.9.4 里所有 `qwen*` 模板都用 `tool_format="qwen"`，产出的是
JSON 体：`<tool_call>\n{"name": ..., "arguments": {...}}\n</tool_call>`。
两者不兼容，**且失败是静默的** —— `parse_output` 找不到 `<function=` 就
`continue`，返回一个空的 `ParsedOutput`：前端空白，无异常、无日志。
实证见 `dataset/tests/test_parser_compat.py`。

⚠️ 光有这个文件不够，见文末「只改训练侧是不够的」。

怎么装
------
LLaMA-Factory 没有插件机制，`TOOLS` 是模块级 dict，直接往里塞即可。
在启动训练前 import 一次本模块（例如写进 `src/llamafactory/__init__.py`，
或用 `PYTHONSTARTUP`、或在自定义入口脚本里）：

    import llamafactory_esa_tool_format as esa_fmt
    esa_fmt.install()          # 往 TOOLS 里注册 "esa_xml"

然后把模板的 tool_format 指过去。0.9.4 的模板是 `register_template(...)` 注册的，
最省事的做法是复制一份 qwen3 模板、只改 tool_format：

    from llamafactory.data.template import TEMPLATES
    import copy
    t = copy.deepcopy(TEMPLATES["qwen3"])
    t.format_tools.tool_format = "esa_xml"
    t.format_function.tool_format = "esa_xml"
    TEMPLATES["qwen3_esa"] = t

训练配置里写 `template: qwen3_esa`。

⚠️ 别用 `template: qwen3_5` —— 0.9.4 里**没有**这个模板，会直接报错。
"""

from __future__ import annotations

import json
import re
from typing import Any

# ---------------------------------------------------------------------------
# 提示词：必须描述 XML 语法
# ---------------------------------------------------------------------------
# Qwen 原版这一段写的是「return a json object ...」。如果照抄，提示词教 JSON、
# 训练目标是 XML，两者自相矛盾 —— 模型在提示词和监督信号之间二选一，
# 而这种冲突不会报错，只会让线上偶发地吐出 JSON。所以这段必须跟着换。
#
# 语法示例抄自 LLaMA-Factory 的 SEED_TOOL_PROMPT（tool_utils.py:87-94）——
# seed_oss 用的就是同一套 `<function=>/<parameter=>`，只是外层标签是
# `<seed:tool_call>`。这不是我编的形状，是现成的。
ESA_TOOL_PROMPT = (
    "\n\n# Tools\n\nYou may call one or more functions to assist with the user query.\n\n"
    "You are provided with function signatures within <tools></tools> XML tags:\n<tools>{tool_text}"
    "\n</tools>\n\n工具调用请遵循如下格式:\n<tool_call>\n<function=example_function_name>\n"
    "<parameter=example_parameter_1>\nvalue_1\n</parameter>\n"
    "<parameter=example_parameter_2>\nThis is the value for the second parameter\n"
    "that can span\nmultiple lines\n</parameter>\n</function>\n</tool_call>"
)


# ---------------------------------------------------------------------------
# 纯函数：不依赖 llamafactory，可以单独测
# ---------------------------------------------------------------------------


def render_arguments_value(value: Any) -> str:
    """一个参数值怎么写进 <parameter> 体。

    与 `dataset/esa/render.py:_wire_tool_call_xml` 必须逐字一致 ——
    那份是评测和 parser 兼容测试用的参考实现，两边漂了就等于没测。

    字符串原样写；其余（数字/布尔/数组/对象）走 JSON。这样后端
    `_try_cast` 才能还原成原类型：它先试 `json.loads`，失败才当字符串。
    """
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def format_tool_calls(calls: list[tuple[str, dict[str, Any]]]) -> str:
    """把 (函数名, 参数 dict) 列表渲染成后端认的 XML。"""
    blocks = []
    for name, arguments in calls:
        parts = [f"<tool_call>\n<function={name}>"]
        for key, value in arguments.items():
            parts.append(f"<parameter={key}>\n{render_arguments_value(value)}\n</parameter>")
        parts.append("</function>\n</tool_call>")
        blocks.append("\n".join(parts))
    return "\n".join(blocks)


# 这两个正则与后端 parser.py:47/57/64 逐字一致。别"顺手优化" ——
# 抽取器必须和后端**一样宽松**，否则训练侧自测能过、线上照样解析不出来。
_BLOCK_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_FUNC_RE = re.compile(r"<function=([^>\s]+)>")
_PARAM_RE = re.compile(r"<parameter=([^>\s]+)>\s*(.*?)\s*</parameter>", re.DOTALL)


def _try_cast(value: str) -> Any:
    """复刻后端 `parser.py:_try_cast`（含 True/False/None 那三个别名）。"""
    value = value.strip()
    if not value:
        return ""

    aliases = {"true": True, "false": False, "none": None, "null": None}
    normalized = value.casefold()
    if normalized in aliases:
        return aliases[normalized]

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def extract_tool_calls(content: str) -> list[tuple[str, dict[str, Any]]] | None:
    """XML → [(函数名, 参数 dict)]。没有工具调用时返回 None。

    ⚠️ 这里没有 schema，所以类型还原只能走 `_try_cast`。后端在有 schema 时
    会额外做一步：声明为 string 的参数**不 cast**（parser.py:76-83）。
    也就是说 `{"course": "2024"}` 这种「字符串类型但内容像数字」的参数，
    本函数会还原成 int 2024，后端会保留字符串 "2024"。
    训练侧用不到 schema，评测请一律以 `esa.backend_parser` 为准。
    """
    blocks = _BLOCK_RE.findall(content)
    if not blocks:
        return None

    out: list[tuple[str, dict[str, Any]]] = []
    for block in blocks:
        func = _FUNC_RE.search(block)
        if not func:
            continue
        args = {k: _try_cast(v) for k, v in _PARAM_RE.findall(block)}
        out.append((func.group(1), args))
    return out or None


# ---------------------------------------------------------------------------
# 往 LLaMA-Factory 里注册
# ---------------------------------------------------------------------------


def install() -> None:
    """把 `esa_xml` 注册进 llamafactory 的 TOOLS。没装 llamafactory 时直接报错。"""
    from llamafactory.data.tool_utils import TOOLS, FunctionCall, ToolUtils

    class EsaXmlToolUtils(ToolUtils):
        """ESA 后端 `parse_output` 期望的 XML 工具协议。"""

        @staticmethod
        def tool_formatter(tools: list[dict[str, Any]]) -> str:
            tool_text = ""
            for tool in tools:
                wrapped = tool if tool.get("type") == "function" else {"type": "function", "function": tool}
                tool_text += "\n" + json.dumps(wrapped, ensure_ascii=False)
            return ESA_TOOL_PROMPT.format(tool_text=tool_text)

        @staticmethod
        def function_formatter(functions: list[FunctionCall]) -> str:
            # FunctionCall.arguments 是 JSON **字符串**，不是 dict
            return format_tool_calls([(name, json.loads(arguments)) for name, arguments in functions])

        @staticmethod
        def tool_extractor(content: str) -> str | list[FunctionCall]:
            calls = extract_tool_calls(content)
            if calls is None:
                return content
            return [
                FunctionCall(name, json.dumps(args, ensure_ascii=False)) for name, args in calls
            ]

    TOOLS["esa_xml"] = EsaXmlToolUtils()


# ---------------------------------------------------------------------------
# 只改训练侧是不够的 —— 读完再决定要不要用这个文件
# ---------------------------------------------------------------------------
#
# 线上那条路径是 `backend/core/services/vllm_service.py:81`：
#
#     self.tokenizer.apply_chat_template(messages, tools=tools, add_generation_prompt=True)
#
# **全仓没有任何自定义 chat template**（已 grep 核实），所以用的是模型自带的
# Qwen 模板 —— 而它注入的工具说明教模型输出 **JSON**。
#
# 于是「训练侧改 XML」只解决了一半：
#   训练时模型学会 XML，上线后提示词又告诉它输出 JSON，两个信号打架。
# 要走这条路，**serving 侧也必须换成教 XML 的模板**（给 vLLM 传
# `chat_template=`，或把上面 ESA_TOOL_PROMPT 那段做成 jinja 模板）。
# 也就是说方案 A 是**两处改动**，不是一处。
#
# 另一条路（方案 B）：让 `parse_output` 同时接受 Qwen 的 JSON 体。
# 一个文件、一处改动，而且与 vLLM 已经在用的模板天然对齐；
# 现有 XML 分支保留即可向后兼容，后端 tests/test_parser.py 不受影响。
#
# 这两条的成本差得很远，**该由后端决定**。本文件把方案 A 备好，
# 是为了让这个决定不必再等实现 —— 不是替他们做决定。
