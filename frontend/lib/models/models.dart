// ESA 数据模型 —— 对话与消息 结构对齐 API.md 与设计 README 的 state 说明

enum MessageRole { user, assistant }

/// 工具调用块 显示在助手正文之前
class ToolInvocation {
  ToolInvocation({
    required this.name,
    required this.output,
    this.durationMs,
  });

  final String name; // 例如 rag.search
  final String output; // 等宽字体展示的内容
  final int? durationMs; // 耗时 毫秒
}

/// 单条消息
class ChatMessage {
  ChatMessage({
    required this.id,
    required this.role,
    this.text = '',
    this.tool,
    this.typing = false,
  });

  final String id;
  final MessageRole role;
  String text;
  ToolInvocation? tool;
  bool typing; // 正在流式输出 末尾显示光标

  bool get isUser => role == MessageRole.user;
}

/// 一个历史对话
class ChatConversation {
  ChatConversation({
    required this.id,
    required this.title,
    required this.updatedAt,
    this.pinned = false,
  });

  final String id;
  String title;
  DateTime updatedAt;
  bool pinned; // 置顶 后端暂无字段 先本地保存
}
