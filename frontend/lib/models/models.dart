// ESA 数据模型 —— 对话与消息 字段对齐 API.md 的 JSON 契约

import 'package:flutter/foundation.dart';

int _seq = 0;
String _nextId() => 'm${_seq++}';

class UserPreferences {
  const UserPreferences({
    this.preferredStyle = 'concise',
    this.preferredTone = 'friendly',
    this.customInstruction = '',
  });

  final String preferredStyle;
  final String preferredTone;
  final String customInstruction;

  factory UserPreferences.fromJson(Map<String, dynamic> json) {
    return UserPreferences(
      preferredStyle: json['preferred_style'] as String? ?? 'concise',
      preferredTone: json['preferred_tone'] as String? ?? 'friendly',
      customInstruction: json['custom_instruction'] as String? ?? '',
    );
  }
}

class UserProfile {
  const UserProfile({
    this.major = 'cs',
    this.grade = '',
    this.currentWeek = 1,
    this.totalWeeks = 16,
    this.profileEnabled = false,
  });

  final String major;
  final String grade;
  final int currentWeek;
  final int totalWeeks;
  final bool profileEnabled;

  factory UserProfile.fromJson(Map<String, dynamic> json) {
    final explicit = <String, dynamic>{};
    final rawExplicit = json['explicit'];
    if (rawExplicit is List) {
      for (final item in rawExplicit.whereType<Map>()) {
        final field = item['field'];
        if (field is String) explicit[field] = item['value'];
      }
    }

    dynamic value(String key) => json[key] ?? explicit[key];

    return UserProfile(
      major: value('major') as String? ?? 'cs',
      grade: value('grade') as String? ?? '',
      currentWeek: (value('current_week') as num?)?.toInt() ?? 1,
      totalWeeks: (value('total_weeks') as num?)?.toInt() ?? 18,
      profileEnabled: value('profile_enabled') as bool? ?? true,
    );
  }
}

class MasteryPoint {
  const MasteryPoint({required this.name, required this.masteryLevel});

  final String name;
  final double masteryLevel;

  factory MasteryPoint.fromJson(Map<String, dynamic> json) => MasteryPoint(
    name: (json['name'] ?? json['kp_id'] ?? '未知知识点').toString(),
    masteryLevel: (json['mastery_level'] as num?)?.toDouble() ?? 0,
  );
}

class MasteryReport {
  const MasteryReport({
    required this.totalPoints,
    required this.averageMastery,
    required this.weakPoints,
    required this.strongPoints,
    required this.stalePoints,
  });

  final int totalPoints;
  final double averageMastery;
  final List<MasteryPoint> weakPoints;
  final List<MasteryPoint> strongPoints;
  final List<MasteryPoint> stalePoints;

  factory MasteryReport.fromJson(Map<String, dynamic> json) {
    List<MasteryPoint> points(String key) => (json[key] as List? ?? const [])
        .whereType<Map>()
        .map((item) => MasteryPoint.fromJson(Map<String, dynamic>.from(item)))
        .toList();
    return MasteryReport(
      totalPoints: (json['total_points'] as num?)?.toInt() ?? 0,
      averageMastery: (json['avg_mastery'] as num?)?.toDouble() ?? 0,
      weakPoints: points('weak_points'),
      strongPoints: points('strong_points'),
      stalePoints: points('stale_points'),
    );
  }
}

class CoreMemoryItem {
  const CoreMemoryItem({
    required this.key,
    required this.content,
    required this.category,
  });

  final String key;
  final String content;
  final String category;

  factory CoreMemoryItem.fromJson(Map<String, dynamic> json) => CoreMemoryItem(
    key: json['memory_key'] as String? ?? '',
    content: json['content'] as String? ?? '',
    category: json['category'] as String? ?? 'general',
  );
}

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
class ChatMessage extends ChangeNotifier {
  ChatMessage({
    required this.id,
    required this.role,
    this.text = '',
    this.name,
    this.createdAt,
    this.typing = false,
    this.markdown = false,
    this.reasoning = '',
  });

  final String id;
  final MessageRole role;
  String text;
  final String? name; // 仅 tool 消息有 工具名
  final String? createdAt;
  bool typing; // 等待后端回复时显示光标
  final bool markdown; // 仅前端使用：用户是否通过 Markdown 模式发送
  String reasoning; // 后端可选返回：模型思考内容

  bool get isUser => role == MessageRole.user;
  bool get isTool => role == MessageRole.tool;

  factory ChatMessage.fromJson(Map<String, dynamic> j) {
    return ChatMessage(
      id: j['id']?.toString() ?? _nextId(),
      role: roleFromString(j['role'] as String? ?? 'assistant'),
      text: j['content'] as String? ?? '',
      name: j['name'] as String?,
      createdAt: j['created_at'] as String?,
      reasoning: (j['reasoning'] ?? j['thinking']) as String? ?? '',
    );
  }

  static ChatMessage user(String text, {bool markdown = false}) => ChatMessage(
    id: _nextId(),
    role: MessageRole.user,
    text: text,
    markdown: markdown,
  );

  static ChatMessage typingPlaceholder() =>
      ChatMessage(id: _nextId(), role: MessageRole.assistant, typing: true);
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
