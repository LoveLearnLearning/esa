// ESA 数据模型 —— 对话与消息 字段对齐 API.md 的 JSON 契约

int _seq = 0;
String _nextId() => 'm${_seq++}';

enum MessageRole { user, assistant, tool }

MessageRole roleFromString(String r) {
  switch (r) {
    case 'user':
      return MessageRole.user;
    case 'tool':
      return MessageRole.tool;
    default:
      return MessageRole.assistant;
  }
}

/// 单条消息 对应 GET /conversations/{id}/messages 返回的元素
class ChatMessage {
  ChatMessage({
    required this.id,
    required this.role,
    this.text = '',
    this.name,
    this.createdAt,
    this.typing = false,
  });

  final String id;
  final MessageRole role;
  String text;
  final String? name; // 仅 tool 消息有 工具名
  final String? createdAt;
  bool typing; // 等待后端回复时显示光标

  bool get isUser => role == MessageRole.user;
  bool get isTool => role == MessageRole.tool;

  factory ChatMessage.fromJson(Map<String, dynamic> j) {
    return ChatMessage(
      id: j['id']?.toString() ?? _nextId(),
      role: roleFromString(j['role'] as String? ?? 'assistant'),
      text: j['content'] as String? ?? '',
      name: j['name'] as String?,
      createdAt: j['created_at'] as String?,
    );
  }

  static ChatMessage user(String text) =>
      ChatMessage(id: _nextId(), role: MessageRole.user, text: text);

  static ChatMessage typingPlaceholder() => ChatMessage(
        id: _nextId(),
        role: MessageRole.assistant,
        typing: true,
      );
}

/// 一个历史对话 对应 /conversations 的元素
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
  bool pinned; // 置顶 后端暂无字段 仅前端本地状态

  factory ChatConversation.fromJson(Map<String, dynamic> j) {
    return ChatConversation(
      id: j['conversation_id'] as String,
      title: (j['title'] as String?) ?? '新对话',
      updatedAt:
          DateTime.tryParse(j['updated_at'] as String? ?? '')?.toLocal() ??
              DateTime.now(),
    );
  }
}
