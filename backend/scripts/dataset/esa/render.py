# backend/scripts/dataset/esa/render.py

"""IR → 训练数据 / 线上文本 的渲染。

两个出口：

1. to_sharegpt()  —— 产出喂给 LLaMA-Factory 的 ShareGPT 记录。
   注意：ShareGPT 文件本身是「格式无关」的，function_call 的 value 永远写成
   {"name":..., "arguments":{...}} 这个 JSON。真正决定线上文本长什么样的是
   LLaMA-Factory 的 tool_format（见 data/formatter.py:104-108 → data/tool_utils.py）。
   所以后端最终选 JSON 还是 XML，这份数据都不用重造。

2. render_wire() —— 复刻模型实际看到 / 实际产出的文本。
   用途是在没有 GPU、没下权重的情况下，先拿它去喂后端的 parse_output()，
   直接验证「训练出来的模型输出能不能被后端解析」。
"""

from __future__ import annotations

import json
import random
from typing import Any

from .ir import (
    ROLE_ASSISTANT,
    ROLE_TOOL_CALL,
    ROLE_TOOL_RESULT,
    ROLE_USER,
    Sample,
)

# IR 角色 → ShareGPT from 标签。
# 必须和 LLaMA-Factory 的默认 tag 一致（src/llamafactory/data/parser.py:58-64），
# 尤其注意是 "function_call" 不是 "function" —— 写成 "function" 整条样本会被静默跳过。
ROLE_TO_SHAREGPT = {
    ROLE_USER: "human",
    ROLE_TOOL_CALL: "function_call",
    ROLE_TOOL_RESULT: "observation",
    ROLE_ASSISTANT: "gpt",
}

# 工具区提示词，用于线上文本预览（render_wire）。
#
# ⚠️ 2026-08-16：下面这份 `QWEN_TOOL_PROMPT` 是 **0.9.4 `qwen` 系模板**用的，
# 教模型产出 JSON 体。**我们实际要用的是 0.9.5 的 `qwen3_5` 模板**，
# 它配的是 `QWEN35_TOOL_PROMPT`（教 XML），见下面第二个常量。
#
# 为什么两份都留着：`render_wire(tool_format=...)` 两种形状都要能预览 ——
# `test_parser_compat.py` 正是靠"喂 JSON 给后端会静默失败"这条来钉住 P0-1 的。
#
# ⚠️ 提示词只出现在 system 段，`assistant_wire_segments()` 取的是
# `<|im_start|>assistant\n` 之后的部分，所以**它不影响 parser 测试的结论**，
# 只影响预览文本的保真度。
QWEN_TOOL_PROMPT = (
    "\n\n# Tools\n\nYou may call one or more functions to assist with the user query.\n\n"
    "You are provided with function signatures within <tools></tools> XML tags:\n<tools>{tool_text}"
    "\n</tools>\n\nFor each function call, return a json object with function name and arguments within "
    """<tool_call></tool_call> XML tags:\n<tool_call>\n{{"name": <function-name>, """
    """"arguments": <args-json-object>}}\n</tool_call>"""
)


# 抄自 LLaMA-Factory 0.9.5 src/llamafactory/data/tool_utils.py:88-101（QWEN35_TOOL_PROMPT）。
# 这是 `qwen3_5` 模板真正用的那份 —— 它教模型产出 XML，和后端 parse_output 对齐。
QWEN35_TOOL_PROMPT = (
    "\n\n# Tools\n\nYou have access to the following functions:\n\n<tools>{tool_text}"
    "\n</tools>\n\nIf you choose to call a function ONLY reply in the following format with NO suffix:\n\n"
    "<tool_call>\n<function=example_function_name>\n<parameter=example_parameter_1>\nvalue_1\n</parameter>\n"
    "<parameter=example_parameter_2>\nThis is the value for the second parameter\nthat can span\nmultiple lines\n"
    "</parameter>\n</function>\n</tool_call>\n\n<IMPORTANT>\nReminder:\n"
    "- Function calls MUST follow the specified format: "
    "an inner <function=...></function> block must be nested within <tool_call></tool_call> XML tags\n"
    "- Required parameters MUST be specified\n"
    "- You may provide optional reasoning for your function call in natural language "
    "BEFORE the function call, but NOT after\n"
    "- If there is no function call available, answer the question like normal with your current knowledge "
    "and do not tell the user about function calls\n</IMPORTANT>"
)

# tool_format → 该用哪份工具区提示词。预览要保真就得配对，不能混用。
TOOL_PROMPTS = {"qwen": QWEN_TOOL_PROMPT, "xml": QWEN35_TOOL_PROMPT}


def pick_tool_names(
    required: list[str],
    all_names: list[str],
    rng: random.Random,
    lo: int = 4,
    hi: int = 10,
) -> list[str]:
    """为一条样本挑选 tools 字段里出现的工具子集，并打乱顺序。

    必含本样本真正要调用的工具，其余为干扰项。这么做有两个目的：
    - 防止模型过拟合到「工具永远全都在」和固定的位置顺序
    - 压住 prompt 长度（22 个工具全塞进去，光工具区就约 4000 token）
    """
    required = list(dict.fromkeys(required))
    pool = [n for n in all_names if n not in required]
    target = max(len(required), rng.randint(lo, hi))
    n_extra = min(len(pool), target - len(required))
    chosen = required + rng.sample(pool, n_extra)
    rng.shuffle(chosen)
    return chosen


def _tools_field(sample: Sample, by_name: dict[str, dict[str, Any]]) -> str:
    """tools 列必须是序列化后的 JSON 字符串，不是对象。"""
    picked = [by_name[n] for n in sample.tool_names if n in by_name]
    return json.dumps(picked, ensure_ascii=False)


def _tool_call_value(turn) -> str:
    """function_call 的 value。

    单调用写成对象，并行调用写成数组 —— LLaMA-Factory 两种都吃
    （src/llamafactory/data/formatter.py:104-108）。
    """
    payload = [{"name": c.name, "arguments": c.arguments} for c in turn.calls]
    if len(payload) == 1:
        return json.dumps(payload[0], ensure_ascii=False)
    return json.dumps(payload, ensure_ascii=False)


# observation 的序列化方式。必须逐字匹配线上，否则模型推理时会遇到没见过的观测格式。
#
# 线上现在是 `json.dumps(result, ensure_ascii=False, default=str)`
# （backend/agent/agent.py:48-54 的 serialize_tool_result）。
#
# ~~线上 agent.py 是 `result_text = str(result)`，即 Python repr：单引号、True/None~~
# → **后端已于 2026-08-11 改成标准 JSON**（正是我们在 `docs/后端问题反馈.md` 里提的建议：
#   Qwen 的工具调用能力是在 JSON 工具结果上训出来的，喂 Python repr 等于让它解析陌生格式）。
#   这个开关从 "repr" 切到 "json"，全部样本要重渲染。
#
# `default=str` 只在工具返回 datetime/Path 这类不可 JSON 化的值时才起作用。
# 我们的观测值全部来自真实执行且都是纯 JSON 类型，所以这里不需要它 ——
# 真需要的那天，下面会直接抛 TypeError 而不是悄悄写出一个和线上不同的字符串。
OBSERVATION_FORMAT = "json"


def _serialize_result(content) -> str:
    """逐字复刻 `serialize_tool_result`（backend/agent/agent.py:48-54）。

    ⚠️ 这里以前有一句 `if isinstance(content, str): return content`。
    在 `str(result)` 时代它是对的（`str("abc") == "abc"`），换成 json.dumps 之后**就错了**：

        json.dumps("北京: 26 摄氏度 晴朗") == '"北京: 26 摄氏度 晴朗"'   ← 带引号

    返回字符串的工具（load_skill / get_time / get_weather，以及全部
    `[Error]: ...` 失败观测）线上都会带上这对引号。少了引号就是模型没见过的格式。
    这条捷径正是 5.10/5.12 那一类"看起来合理"的假设，所以整句删掉，
    一律走和后端同一个调用。`observation_format` 那组黄金样例把它钉死
    （data/cache/math_real.json，test_fixture_contract.py 逐条比对）。
    """
    if OBSERVATION_FORMAT == "json":
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _tool_result_value(turn) -> str:
    """observation 的 value。

    角色必须严格交替，所以一条 function_call 后面只能跟一条 observation。
    ⚠️ 线上对并行调用是**每个结果单独一条 tool 消息**（agent.py 的
    `for tool_call in tool_calls:` 循环），与这里合并成一条的做法不一致。
    所以在确认渲染方式之前，不要生成并行调用样本。
    """
    if len(turn.results) == 1:
        return _serialize_result(turn.results[0].content)
    return _serialize_result([{"name": r.name, "content": r.content} for r in turn.results])


def to_sharegpt(sample: Sample, by_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """IR → 一条 ShareGPT 记录。"""
    conversations = []
    for turn in sample.turns:
        tag = ROLE_TO_SHAREGPT[turn.role]
        if turn.role == ROLE_TOOL_CALL:
            value = _tool_call_value(turn)
        elif turn.role == ROLE_TOOL_RESULT:
            value = _tool_result_value(turn)
        else:
            value = turn.content or ""
        conversations.append({"from": tag, "value": value})

    return {
        "conversations": conversations,
        "system": sample.system,
        "tools": _tools_field(sample, by_name),
    }


# --------------------------------------------------------------------------
# 线上文本预览：用来在没有权重的情况下验证后端 parser 兼容性
# --------------------------------------------------------------------------


def _wire_tool_call_qwen(turn) -> str:
    """Qwen 原生：<tool_call>{json}</tool_call>（tool_utils.py:423-428）"""
    blocks = [
        "<tool_call>\n" + json.dumps({"name": c.name, "arguments": c.arguments}, ensure_ascii=False) + "\n</tool_call>"
        for c in turn.calls
    ]
    return "\n".join(blocks)


def _wire_tool_call_xml(turn) -> str:
    """后端 parse_output 目前期望的格式：<tool_call><function=X><parameter=K>v</parameter></function></tool_call>"""
    blocks = []
    for c in turn.calls:
        parts = [f"<tool_call>\n<function={c.name}>"]
        for k, v in c.arguments.items():
            sv = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            parts.append(f"<parameter={k}>\n{sv}\n</parameter>")
        parts.append("</function>\n</tool_call>")
        blocks.append("\n".join(parts))
    return "\n".join(blocks)


WIRE_FORMATS = {"qwen": _wire_tool_call_qwen, "xml": _wire_tool_call_xml}


def render_wire(
    sample: Sample,
    by_name: dict[str, dict[str, Any]],
    tool_format: str = "qwen",
    with_empty_think: bool = True,
) -> str:
    """复刻 qwen3 模板渲染后的完整对话文本。

    slots 抄自 LLaMA-Factory src/llamafactory/data/template.py:1904-1919。
    with_empty_think 对应 ReasoningTemplate 自动补空 CoT 的行为
    （template.py:424-431）—— 这正是让后端 StreamOutputParser 能正常工作的前提。
    """
    emit_call = WIRE_FORMATS[tool_format]
    tool_text = "".join(
        "\n" + json.dumps(by_name[n], ensure_ascii=False) for n in sample.tool_names if n in by_name
    )
    system = sample.system + TOOL_PROMPTS[tool_format].format(tool_text=tool_text)

    out = [f"<|im_start|>system\n{system}<|im_end|>\n"]
    think = "<think>\n\n</think>\n\n" if with_empty_think else ""

    for turn in sample.turns:
        if turn.role == ROLE_USER:
            out.append(f"<|im_start|>user\n{turn.content}<|im_end|>\n<|im_start|>assistant\n")
        elif turn.role == ROLE_TOOL_CALL:
            out.append(f"{think}{emit_call(turn)}<|im_end|>\n")
        elif turn.role == ROLE_TOOL_RESULT:
            out.append(
                f"<|im_start|>user\n<tool_response>\n{_tool_result_value(turn)}\n"
                f"</tool_response><|im_end|>\n<|im_start|>assistant\n"
            )
        else:
            out.append(f"{think}{turn.content}<|im_end|>\n")

    return "".join(out)


def assistant_wire_segments(sample: Sample, by_name, tool_format: str = "qwen") -> list[str]:
    """拆出每一段模型输出 —— 这些就是逐次喂给后端 parse_output() 的东西。

    一次工具调用的对话会有两段：第一段是工具调用，第二段是拿到结果后的最终回答。
    """
    text = render_wire(sample, by_name, tool_format)
    segments = []
    for chunk in text.split("<|im_start|>assistant\n")[1:]:
        segments.append(chunk.split("<|im_end|>")[0])
    return segments


def last_assistant_wire(sample: Sample, by_name, tool_format: str = "qwen") -> str:
    """只取最后一段模型输出（最终回答）。"""
    return assistant_wire_segments(sample, by_name, tool_format)[-1]
