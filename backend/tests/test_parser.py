# backend/tests/test_parser.py

"""验证 `parser` 相关行为与回归场景。"""

import unittest

from backend.core.utils.parser import StreamOutputParser, parse_output


class ParseOutputTests(unittest.TestCase):
    """验证 `parse output tests` 相关行为。"""
    MATH_SOLVER_SCHEMA = {
        "type": "function",
        "function": {
            "name": "math_solver",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string"},
                    "lower": {"type": "string"},
                    "upper": {"type": "string"},
                    "point": {"type": "string"},
                    "order": {"type": "integer"},
                },
            },
        },
    }

    def test_tool_arguments_support_json_values(self) -> None:
        """验证 `tool_arguments_support_json_values` 场景。"""
        parsed = parse_output(
            """</think>
<tool_call>
<function=example.tool>
<parameter=count>3</parameter>
<parameter=enabled>true</parameter>
<parameter=items>[\"a\", \"b\"]</parameter>
</function>
</tool_call>"""
        )

        self.assertEqual(len(parsed.tool_calls), 1)
        self.assertEqual(parsed.tool_calls[0].name, "example.tool")
        self.assertEqual(
            parsed.tool_calls[0].arguments,
            {"count": 3, "enabled": True, "items": ["a", "b"]},
        )

    def test_tool_arguments_accept_python_style_literals(self) -> None:
        """验证 `tool_arguments_accept_python_style_literals` 场景。"""
        parsed = parse_output(
            """</think>
<tool_call>
<function=record_learning_evidence>
<parameter=correct>True</parameter>
<parameter=independent>False</parameter>
<parameter=self_confidence>None</parameter>
</function>
</tool_call>"""
        )

        self.assertEqual(
            parsed.tool_calls[0].arguments,
            {"correct": True, "independent": False, "self_confidence": None},
        )

    def test_tool_arguments_follow_declared_schema_types(self) -> None:
        """验证 `tool_arguments_follow_declared_schema_types` 场景。"""
        parsed = parse_output(
            """</think>
<tool_call>
<function=math_solver>
<parameter=expression>x ** 2</parameter>
<parameter=lower>0</parameter>
<parameter=upper>1</parameter>
<parameter=point>null</parameter>
<parameter=order>2</parameter>
</function>
</tool_call>""",
            tool_schemas=[self.MATH_SOLVER_SCHEMA],
        )

        self.assertEqual(
            parsed.tool_calls[0].arguments,
            {
                "expression": "x ** 2",
                "lower": "0",
                "upper": "1",
                "point": "null",
                "order": 2,
            },
        )

    def test_invalid_schema_value_does_not_crash_parser(self) -> None:
        """验证 `invalid_schema_value_does_not_crash_parser` 场景。"""
        parsed = parse_output(
            """</think>
<tool_call>
<function=math_solver>
<parameter=order>two</parameter>
</function>
</tool_call>""",
            tool_schemas=[self.MATH_SOLVER_SCHEMA],
        )

        self.assertEqual(parsed.tool_calls[0].arguments, {"order": "two"})

    def test_qwen_native_json_tool_call_is_parsed(self) -> None:
        """Qwen 原生 JSON Tool 格式不能被静默丢弃。"""
        parsed = parse_output(
            """</think>
<tool_call>
{"name":"math_solver","arguments":{"expression":"x ** 2","order":2}}
</tool_call>""",
            tool_schemas=[self.MATH_SOLVER_SCHEMA],
        )

        self.assertEqual(len(parsed.tool_calls), 1)
        self.assertEqual(parsed.tool_calls[0].name, "math_solver")
        self.assertEqual(
            parsed.tool_calls[0].arguments,
            {"expression": "x ** 2", "order": 2},
        )

    def test_qwen_json_tool_call_list_is_parsed(self) -> None:
        """单个 Tool block 中的 JSON 调用列表也应完整保留。"""
        parsed = parse_output(
            """</think>
<tool_call>
[{"name":"first","arguments":{"value":1}},
 {"name":"second","arguments":{"value":2}}]
</tool_call>"""
        )

        self.assertEqual(
            [(call.name, call.arguments) for call in parsed.tool_calls],
            [("first", {"value": 1}), ("second", {"value": 2})],
        )


class StreamOutputParserTests(unittest.TestCase):
    """验证 `stream output parser tests` 相关行为。"""
    @staticmethod
    def parse_chunks(chunks: list[str]) -> tuple[str, str, str]:
        """解析 `chunks` 相关数据。

        Args:
            chunks: list[str] => `chunks` 参数。

        Returns:
            tuple[str, str, str] => 处理结果。
        """
        parser = StreamOutputParser()
        reasoning_parts: list[str] = []
        content_parts: list[str] = []

        for chunk in chunks:
            for event, delta in parser.feed(chunk):
                if event == "reasoning":
                    reasoning_parts.append(delta)
                elif event == "content":
                    content_parts.append(delta)

        for event, delta in parser.finish():
            if event == "reasoning":
                reasoning_parts.append(delta)
            elif event == "content":
                content_parts.append(delta)

        return "".join(reasoning_parts), "".join(content_parts), parser.raw_text

    def test_streams_reasoning_and_content_across_split_tags(self) -> None:
        """验证 `streams_reasoning_and_content_across_split_tags` 场景。"""
        raw = "<think>分析题目</think>\n\n最终答案"
        chunks = [raw[index : index + 2] for index in range(0, len(raw), 2)]

        reasoning, content, collected = self.parse_chunks(chunks)

        self.assertEqual(reasoning, "分析题目")
        self.assertEqual(content, "\n\n最终答案")
        self.assertEqual(collected, raw)

    def test_hides_tool_call_from_visible_events(self) -> None:
        """验证 `hides_tool_call_from_visible_events` 场景。"""
        raw = """先调用工具</think>
<tool_call>
<function=calculator>
<parameter=expression>1 + 2</parameter>
</function>
</tool_call>"""
        chunks = [raw[index : index + 3] for index in range(0, len(raw), 3)]

        reasoning, content, collected = self.parse_chunks(chunks)

        self.assertEqual(reasoning, "先调用工具")
        self.assertEqual(content, "")
        self.assertEqual(collected, raw)

    def test_hides_tool_call_that_follows_visible_content(self) -> None:
        """验证 `hides_tool_call_that_follows_visible_content` 场景。"""
        raw = """分析完成</think>
平均情况需要计算期望值。
<tool_call>
<function=math_solver>
<parameter=expression>n * log(n, 2)</parameter>
</function>
</tool_call>"""
        chunks = [raw[index : index + 2] for index in range(0, len(raw), 2)]

        reasoning, content, collected = self.parse_chunks(chunks)

        self.assertEqual(reasoning, "分析完成")
        self.assertEqual(content, "\n平均情况需要计算期望值。\n")
        self.assertNotIn("<tool_call>", content)
        self.assertNotIn("<function=", content)
        self.assertEqual(collected, raw)

    def test_accepts_think_open_from_generation_output(self) -> None:
        """验证 `accepts_think_open_from_generation_output` 场景。"""
        reasoning, content, _ = self.parse_chunks(
            ["<thi", "nk>推理</thi", "nk>回答"]
        )

        self.assertEqual(reasoning, "推理")
        self.assertEqual(content, "回答")


if __name__ == "__main__":
    unittest.main()
