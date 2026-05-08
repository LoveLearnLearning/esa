"""
prompt.py — Agent Prompt 管理模块
负责：System Prompt 定义、工具描述、历史记录读写、动态 Prompt 构建
"""

import json
from datetime import datetime
from pathlib import Path

# ──────────────────────────────────────────
# 基础配置
# ──────────────────────────────────────────

AGENT_NAME = "StudyBuddy"
MAX_ITERATIONS = 5
DEFAULT_LANGUAGE = "zh-CN"


# ──────────────────────────────────────────
# 工具定义
# ──────────────────────────────────────────

TOOLS = [
    {
        "name": "search_web",
        "description": "搜索互联网获取最新信息。当用户询问实时数据、新闻、天气等需要最新信息时使用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "calculator",
        "description": "执行数学计算。当用户需要计算数值结果时使用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "数学表达式，例如 '2 + 3 * 4'",
                }
            },
            "required": ["expression"],
        },
    },
    {
        "name": "get_weather",
        "description": "获取指定城市的天气信息。",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名称，例如 '北京'",
                }
            },
            "required": ["city"],
        },
    },
]


# ──────────────────────────────────────────
# 错误信息
# ──────────────────────────────────────────

ERROR_MESSAGES = {
    "tool_failed": "工具调用失败：{reason}，请稍后重试。",
    "max_iter": f"已达到最大迭代次数（{MAX_ITERATIONS} 次），任务终止。",
    "unknown_tool": "未知工具：{tool_name}",
    "load_failed": "历史记录加载失败：{reason}",
    "save_failed": "历史记录保存失败：{reason}",
}


# ──────────────────────────────────────────
# Prompt 管理类
# ──────────────────────────────────────────


class Prompt:
    """
    管理 Agent 的 Prompt 构建与会话历史。

    Args:
        session_id: 会话唯一标识，用于隔离不同用户的历史记录。
        user_name:  当前用户名，可选，用于个性化 System Prompt。
    """

    # System Prompt 模板（类级别，所有实例共享）
    _SYSTEM_TEMPLATE = """你是 {agent_name}，一个智能助手。今天是 {date}。

## 职责
- 准确理解用户意图，给出清晰、有用的回答
- 合理使用工具获取所需信息
- 不确定时主动说明，不编造信息

## 工具使用原则
- 只在必要时调用工具，不过度使用
- 工具调用失败时，告知用户并尝试其他方式
- 每次最多调用一个工具，等待结果后再决定下一步

## 输出风格
- 语言简洁，重点突出
- 使用中文回复（除非用户使用其他语言）
- 不要在回答中暴露内部思考过程
{extra_section}"""

    def __init__(self, session_id: str = "default", user_name: str = ""):
        self.session_id = session_id
        self.user_name = user_name

        # 会话历史存储目录
        self.session_path = Path.cwd().parent / "data" / "session"
        self.session_path.mkdir(parents=True, exist_ok=True)

    # ── 内部工具方法 ──────────────────────────────────────────

    def _history_path(self) -> Path:
        """返回当前 session 的历史文件路径"""
        return self.session_path / f"{self.session_id}.json"

    def _format_extra_section(self, extra_context: str = "") -> str:
        """构建 System Prompt 的可选补充段落"""
        parts = []
        if self.user_name:
            parts.append(f"\n## 当前用户\n你正在服务的用户是：{self.user_name}")
        if extra_context:
            parts.append(f"\n## 额外上下文\n{extra_context}")
        return "".join(parts)

    # ── 历史记录 ──────────────────────────────────────────

    def load_history(self) -> list[dict]:
        """
        从文件加载历史消息列表。

        Returns:
            消息列表，格式为 [{"role": "user"/"assistant", "content": "..."}, ...]
            文件不存在或解析失败时返回空列表。
        """
        path = self._history_path()
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as e:
            print(ERROR_MESSAGES["load_failed"].format(reason=e))
            return []

    def save_history(self, history: list[dict]) -> None:
        """
        将消息列表持久化到文件。

        Args:
            history: 消息列表，格式同 load_history 返回值。
        """
        try:
            with open(self._history_path(), "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(ERROR_MESSAGES["save_failed"].format(reason=e))

    def update_history(self, user_input: str, response: str) -> None:
        """
        追加一轮对话到历史记录。

        Args:
            user_input: 用户输入。
            response:   助手回复。
        """
        history = self.load_history()
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": response})
        self.save_history(history)

    def clear_history(self) -> None:
        """清空当前 session 的历史记录"""
        self.save_history([])

    # ── Prompt 构建 ──────────────────────────────────────────

    def build_system_prompt(self, extra_context: str = "") -> str:
        """
        构建完整的 System Prompt。

        Args:
            extra_context: 额外上下文信息，追加到 System Prompt 末尾。

        Returns:
            格式化后的 System Prompt 字符串。
        """
        return self._SYSTEM_TEMPLATE.format(
            agent_name=AGENT_NAME,
            date=datetime.now().strftime("%Y-%m-%d"),
            extra_section=self._format_extra_section(extra_context),
        )

    def build_messages(self, user_input: str) -> list[dict]:
        history = self.load_history()
        history.append({"role": "user", "content": user_input})
        return history
