"""不同基座模型的提示词和输出协议适配层。"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from backend.core.utils.models import ParsedOutput, ToolCall
from backend.core.utils.parser import (
    DEEPSEEK_V4_DSML,
    DEEPSEEK_V4_EOS,
    DeepSeekV4StreamOutputParser,
    StreamOutputParser,
    parse_deepseek_v4_output,
    parse_output,
)


class ModelAdapter(Protocol):
    """把项目内部消息格式转换为某个模型的输入/输出协议。"""

    name: str

    def build_prompt(
        self,
        tokenizer: Any,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> str: ...

    def parse_output(self, raw_text: str) -> ParsedOutput: ...

    def create_stream_parser(self) -> StreamOutputParser: ...

    def assistant_message(
        self,
        parsed: ParsedOutput,
        raw_text: str,
    ) -> dict[str, Any]: ...


class QwenXmlAdapter:
    """项目原有 Qwen/XML 工具调用协议，保留以兼容现有模型。"""

    name = "qwen_xml"

    def build_prompt(
        self,
        tokenizer: Any,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> str:
        return tokenizer.apply_chat_template(
            messages,
            tools=tools,
            tokenize=False,
            add_generation_prompt=True,
        )

    def parse_output(self, raw_text: str) -> ParsedOutput:
        return parse_output(raw_text)

    def create_stream_parser(self) -> StreamOutputParser:
        return StreamOutputParser()

    def assistant_message(
        self,
        parsed: ParsedOutput,
        raw_text: str,
    ) -> dict[str, Any]:
        del parsed
        return {"role": "assistant", "content": raw_text}


class DeepSeekV4Adapter:
    """DeepSeek-V4-Flash-0731 的官方 DSML 协议适配器。

    V4 不提供 Jinja chat template，且将 tool 结果放入后续 user turn 的
    ``<tool_result>`` 块中。因此这里不能复用 Qwen 的 ``apply_chat_template``。
    """

    name = "deepseek_v4"
    _bos = "<｜begin▁of▁sentence｜>"
    _user = "<｜User｜>"
    _assistant = "<｜Assistant｜>"
    _thinking_open = "<think>"
    _thinking_close = "</think>"

    def build_prompt(
        self,
        tokenizer: Any,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> str:
        del tokenizer
        prepared = self._attach_tools_and_merge_results(messages, tools)
        prompt_parts = [self._bos]

        for message in prepared:
            role = message["role"]
            if role == "system":
                prompt_parts.append(message.get("content", ""))
            elif role == "user":
                prompt_parts.append(self._user)
                prompt_parts.append(message.get("content", ""))
            elif role == "assistant":
                prompt_parts.append(self._render_assistant_message(message))
            else:
                raise ValueError(f"DeepSeek-V4 不支持的消息 role: {role!r}")

        if prepared and prepared[-1]["role"] == "user":
            prompt_parts.extend((self._assistant, self._thinking_open))

        return "".join(prompt_parts)

    def parse_output(self, raw_text: str) -> ParsedOutput:
        return parse_deepseek_v4_output(raw_text)

    def create_stream_parser(self) -> StreamOutputParser:
        return DeepSeekV4StreamOutputParser()

    def assistant_message(
        self,
        parsed: ParsedOutput,
        raw_text: str,
    ) -> dict[str, Any]:
        del raw_text
        message: dict[str, Any] = {
            "role": "assistant",
            "content": parsed.content or "",
            "reasoning_content": parsed.reasoning or "",
        }
        if parsed.tool_calls:
            message["tool_calls"] = [
                {
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments,
                            ensure_ascii=False,
                        ),
                    },
                }
                for call in parsed.tool_calls
            ]
        return message

    def _attach_tools_and_merge_results(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """把 OpenAI 风格工具定义放入 system，并把 tool role 合并为 user。"""
        prepared = copy.deepcopy(messages)
        if tools:
            system_message = next(
                (message for message in prepared if message.get("role") == "system"),
                None,
            )
            if system_message is None:
                system_message = {"role": "system", "content": ""}
                prepared.insert(0, system_message)
            system_message["content"] = (
                f"{system_message.get('content', '')}\n\n{self._render_tools(tools)}"
            )

        merged: list[dict[str, Any]] = []
        tool_results: list[str] = []
        for message in prepared:
            if message.get("role") == "tool":
                tool_results.append(
                    f"<tool_result>{message.get('content', '')}</tool_result>"
                )
                continue

            if message.get("role") == "assistant":
                message = self._restore_assistant_tool_call(message)

            if tool_results:
                merged.append(
                    {
                        "role": "user",
                        "content": "\n\n".join(tool_results),
                    }
                )
                tool_results = []
            merged.append(message)

        if tool_results:
            merged.append({"role": "user", "content": "\n\n".join(tool_results)})
        return merged

    def _restore_assistant_tool_call(
        self,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        """将数据库里保存的原始 DSML 回复恢复为结构化 assistant 消息。

        ChatStore 目前只持久化 ``role/content``。工具调用轮会将原始模型输出
        保存为不可见消息；再次生成时在这里还原其 reasoning 与 tool_calls，
        从而不要求变更已有聊天表结构。
        """
        raw_content = message.get("content", "")
        if not isinstance(raw_content, str) or (
            DEEPSEEK_V4_DSML not in raw_content
            and self._thinking_close not in raw_content
        ):
            return message

        parsed = self.parse_output(raw_content)
        message["content"] = parsed.content or ""
        message["reasoning_content"] = parsed.reasoning or ""
        if parsed.tool_calls:
            message["tool_calls"] = [
                {
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments,
                            ensure_ascii=False,
                        ),
                    },
                }
                for call in parsed.tool_calls
            ]
        return message

    def _render_assistant_message(self, message: dict[str, Any]) -> str:
        reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
        content = message.get("content") or ""
        parts = [self._assistant]
        if reasoning:
            parts.extend((self._thinking_open, reasoning, self._thinking_close))
        else:
            parts.append(self._thinking_close)
        parts.append(content)

        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            parts.extend(("\n\n", self._render_tool_calls(tool_calls)))
        parts.append(DEEPSEEK_V4_EOS)
        return "".join(parts)

    def _render_tools(self, tools: list[dict[str, Any]]) -> str:
        definitions = [tool.get("function", tool) for tool in tools]
        schemas = "\n".join(
            json.dumps(definition, ensure_ascii=False) for definition in definitions
        )
        return f"""## Tools

You have access to a set of tools to help answer the user's question. You can invoke tools by writing a "<{DEEPSEEK_V4_DSML}tool_calls>" block like the following:
<{DEEPSEEK_V4_DSML}tool_calls>
<{DEEPSEEK_V4_DSML}invoke name="$TOOL_NAME">
<{DEEPSEEK_V4_DSML}parameter name="$PARAMETER_NAME" string="true|false">$PARAMETER_VALUE</{DEEPSEEK_V4_DSML}parameter>
...
</{DEEPSEEK_V4_DSML}invoke>
</{DEEPSEEK_V4_DSML}tool_calls>

String parameters must use string="true". Numbers, booleans, arrays, and objects must be JSON with string="false".
When thinking is enabled, complete reasoning must be inside <think>...</think> before the tool call or final answer.

### Available Tool Schemas

{schemas}

You MUST strictly follow the defined tool names and parameter schemas."""

    def _render_tool_calls(self, tool_calls: list[dict[str, Any]]) -> str:
        invocations: list[str] = []
        for call in tool_calls:
            function = call.get("function", call)
            name = function.get("name", "")
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"arguments": arguments}

            parameters: list[str] = []
            for key, value in arguments.items():
                is_string = isinstance(value, str)
                rendered_value = (
                    value if is_string else json.dumps(value, ensure_ascii=False)
                )
                parameters.append(
                    f'<{DEEPSEEK_V4_DSML}parameter name="{key}" '
                    f'string="{str(is_string).lower()}">{rendered_value}'
                    f"</{DEEPSEEK_V4_DSML}parameter>"
                )
            rendered_parameters = "\n".join(parameters)
            invocations.append(
                f'<{DEEPSEEK_V4_DSML}invoke name="{name}">\n'
                f"{rendered_parameters}\n"
                f"</{DEEPSEEK_V4_DSML}invoke>"
            )
        rendered_invocations = "\n".join(invocations)
        return (
            f"<{DEEPSEEK_V4_DSML}tool_calls>\n"
            f"{rendered_invocations}\n"
            f"</{DEEPSEEK_V4_DSML}tool_calls>"
        )


def get_model_adapter(
    name: str,
    model_path: str | Path,
) -> ModelAdapter:
    """按显式配置或模型目录名选择适配器。"""
    normalized_name = name.strip().lower().replace("-", "_")
    if normalized_name == "auto":
        path_name = str(model_path).lower().replace("-", "_")
        normalized_name = "deepseek_v4" if "deepseek_v4" in path_name else "qwen_xml"

    adapters: dict[str, Callable[[], ModelAdapter]] = {
        "qwen_xml": QwenXmlAdapter,
        "deepseek_v4": DeepSeekV4Adapter,
    }
    try:
        return adapters[normalized_name]()
    except KeyError as error:
        supported = ", ".join(sorted(adapters))
        raise ValueError(
            f"未知 MODEL_ADAPTER={name!r}，可选值：auto、{supported}"
        ) from error
