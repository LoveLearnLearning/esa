from backend.agent.tools.tool_register import ToolRegistry

tr = ToolRegistry()


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取城市天气",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                    }
                },
                "required": ["city"],
            },
        },
    }
)
def get_weather(city: str) -> str:
    return f"{city}: 26 摄氏度 晴朗"


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "add_two_nums",
            "description": "求两数之和",
            "parameters": {
                "type": "object",
                "properties": {
                    "num1": {
                        "type": "float",
                    },
                    "num2": {
                        "type": "float",
                    },
                },
                "required": ["num1", "num2"],
            },
        },
    }
)
def add_two_num(num1: float, num2: float) -> float:
    return num1 + num2
