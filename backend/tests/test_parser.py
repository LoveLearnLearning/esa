import unittest

from backend.core.utils.parser import StreamOutputParser, parse_output


class ParseOutputTests(unittest.TestCase):
    def test_tool_arguments_support_json_values(self) -> None:
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


class StreamOutputParserTests(unittest.TestCase):
    @staticmethod
    def parse_chunks(chunks: list[str]) -> tuple[str, str, str]:
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
        raw = "<think>分析题目</think>\n\n最终答案"
        chunks = [raw[index : index + 2] for index in range(0, len(raw), 2)]

        reasoning, content, collected = self.parse_chunks(chunks)

        self.assertEqual(reasoning, "分析题目")
        self.assertEqual(content, "\n\n最终答案")
        self.assertEqual(collected, raw)

    def test_hides_tool_call_from_visible_events(self) -> None:
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
        reasoning, content, _ = self.parse_chunks(
            ["<thi", "nk>推理</thi", "nk>回答"]
        )

        self.assertEqual(reasoning, "推理")
        self.assertEqual(content, "回答")


if __name__ == "__main__":
    unittest.main()
