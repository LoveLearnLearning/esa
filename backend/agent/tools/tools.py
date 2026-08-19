# backend/agent/tools/tools.py

"""提供 `tools` 相关功能。"""

from datetime import timezone

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
    """获取 `weather` 相关数据。"""
    return f"{city}: 26 摄氏度 晴朗"


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "获取当前时间",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
)
def get_time() -> str:
    """获取 `time` 相关数据。"""
    from datetime import datetime

    return datetime.now(timezone.utc).strftime("%D-%H:%M:%S")
