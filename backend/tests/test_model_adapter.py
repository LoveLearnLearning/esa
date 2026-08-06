import unittest

from backend.core.utils.model_adapter import DeepSeekV4Adapter, get_model_adapter


class DeepSeekV4AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = DeepSeekV4Adapter()

    def test_parses_reasoning_content_and_dsml_tool_call(self) -> None:
        raw = """先计算。</think>

<｜DSML｜tool_calls>
<｜DSML｜invoke name="calculator">
<｜DSML｜parameter name="expression" string="true">1 + 2</｜DSML｜parameter>
<｜DSML｜parameter name="precision" string="false">3</｜DSML｜parameter>
</｜DSML｜invoke>
</｜DSML｜tool_calls><｜end▁of▁sentence｜>"""

        parsed = self.adapter.parse_output(raw)

        self.assertEqual(parsed.reasoning, "先计算。")
        self.assertEqual(parsed.content, "")
        self.assertEqual(len(parsed.tool_calls), 1)
        self.assertEqual(parsed.tool_calls[0].name, "calculator")
        self.assertEqual(
            parsed.tool_calls[0].arguments,
            {"expression": "1 + 2", "precision": 3},
        )

    def test_stream_hides_dsml_and_end_token_across_chunks(self) -> None:
        raw = """分析</think>最终答案<｜end▁of▁sentence｜>"""
        parser = self.adapter.create_stream_parser()
        events: list[tuple[str, str]] = []

        for index in range(0, len(raw), 2):
            events.extend(parser.feed(raw[index : index + 2]))
        events.extend(parser.finish())

        self.assertEqual(
            "".join(delta for event, delta in events if event == "reasoning"),
            "分析",
        )
        self.assertEqual(
            "".join(delta for event, delta in events if event == "content"),
            "最终答案",
        )

    def test_build_prompt_includes_dsml_and_tool_result(self) -> None:
        prompt = self.adapter.build_prompt(
            tokenizer=None,
            messages=[
                {"role": "system", "content": "你是助手。"},
                {"role": "user", "content": "算 1 + 2"},
                {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "需要计算",
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {
                                "name": "calculator",
                                "arguments": '{"expression": "1 + 2"}',
                            },
                        }
                    ],
                },
                {"role": "tool", "name": "calculator", "content": "3"},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "calculator",
                        "parameters": {"type": "object"},
                    },
                }
            ],
        )

        self.assertIn("<｜DSML｜tool_calls>", prompt)
        self.assertIn('name="calculator"', prompt)
        self.assertIn("<tool_result>3</tool_result>", prompt)
        self.assertTrue(prompt.endswith("<｜Assistant｜><think>"))

    def test_auto_selects_deepseek_adapter(self) -> None:
        adapter = get_model_adapter(
            "auto",
            "/models/DeepSeek-V4-Flash-0731",
        )

        self.assertEqual(adapter.name, "deepseek_v4")


if __name__ == "__main__":
    unittest.main()
