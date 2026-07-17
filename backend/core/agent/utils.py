# backend/core/agent/utils.py


OUTPUT = """
用户询问北京天气怎么样，我需要使用get_weather工具来获取北京的天气信息。这个工具需要一个city参数，用户已经提供了"北京"这个城市名。
</think>

<tool_call>
<function=get_weather>
<parameter=city>
北京
</parameter>
</function>
</tool_call>
"""


def parse_output(llm_output: str) -> dict:
    result: dict = {}
    tokens = [line for line in llm_output.splitlines() if line != ""]
    result["think"] = tokens.pop(0)
    result["parameter"] = []

    while tokens:
        cur = tokens.pop(0)
        if cur == "<tool_call>":
            result["function"] = tokens.pop(0)[10:-1]
            result["parameter"].append((tokens.pop(0)[11:-1], tokens.pop(0)))

    return result


def main() -> None:
    print(parse_output(OUTPUT))


if __name__ == "__main__":
    main()
