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

class ScheduleCourse {
  const ScheduleCourse({
    required this.id,
    required this.name,
    required this.weekday,
    required this.startPeriod,
    required this.endPeriod,
    required this.startWeek,
    required this.endWeek,
    required this.colorValue,
    this.teacher = '',
    this.location = '',
  });

  final String id;
  final String name;
  final String teacher;
  final String location;
  final int weekday;
  final int startPeriod;
  final int endPeriod;
  final int startWeek;
  final int endWeek;
  final int colorValue;

  bool occursInWeek(int week) => week >= startWeek && week <= endWeek;

  Map<String, dynamic> toJson() => {
    'id': id,
    'name': name,
    'teacher': teacher,
    'location': location,
    'weekday': weekday,
    'start_period': startPeriod,
    'end_period': endPeriod,
    'start_week': startWeek,
    'end_week': endWeek,
    'color_value': colorValue,
  };

  factory ScheduleCourse.fromJson(Map<String, dynamic> json) {
    int number(String key, int fallback) =>
        (json[key] as num?)?.toInt() ?? fallback;
    return ScheduleCourse(
      id: json['id']?.toString() ?? _nextId(),
      name: json['name']?.toString() ?? '未命名课程',
      teacher: json['teacher']?.toString() ?? '',
      location: json['location']?.toString() ?? '',
      weekday: number('weekday', 1).clamp(1, 7),
      startPeriod: number('start_period', 1).clamp(1, 24),
      endPeriod: number('end_period', 2).clamp(1, 24),
      startWeek: number('start_week', 1).clamp(1, 30),
      endWeek: number('end_week', 18).clamp(1, 30),
      colorValue: number('color_value', 0xFF2563EB),
    );
  }
}

class ScheduleSettings {
  const ScheduleSettings({
    this.morningPeriodCount = 4,
    this.afternoonPeriodCount = 4,
    this.eveningPeriodCount = 4,
    this.morningStartMinutes = 8 * 60,
    this.afternoonStartMinutes = 14 * 60,
    this.eveningStartMinutes = 19 * 60,
    this.periodDurationMinutes = 45,
    this.breakDurationMinutes = 10,
  });

  final int morningPeriodCount;
  final int afternoonPeriodCount;
  final int eveningPeriodCount;
  final int morningStartMinutes;
  final int afternoonStartMinutes;
  final int eveningStartMinutes;
  final int periodDurationMinutes;
  final int breakDurationMinutes;

  int get totalPeriods =>
      morningPeriodCount + afternoonPeriodCount + eveningPeriodCount;

  int periodStartMinutes(int period) {
    final normalizedPeriod = period.clamp(
      1,
      totalPeriods == 0 ? 1 : totalPeriods,
    );
    final step = periodDurationMinutes + breakDurationMinutes;
    if (normalizedPeriod <= morningPeriodCount) {
      return morningStartMinutes + (normalizedPeriod - 1) * step;
    }
    final afternoonEnd = morningPeriodCount + afternoonPeriodCount;
    if (normalizedPeriod <= afternoonEnd) {
      return afternoonStartMinutes +
          (normalizedPeriod - morningPeriodCount - 1) * step;
    }
    return eveningStartMinutes + (normalizedPeriod - afternoonEnd - 1) * step;
  }

  int periodEndMinutes(int period) =>
      periodStartMinutes(period) + periodDurationMinutes;

  String periodStartLabel(int period) =>
      formatClockMinutes(periodStartMinutes(period));

  String periodEndLabel(int period) =>
      formatClockMinutes(periodEndMinutes(period));

  String courseTimeLabel(int startPeriod, int endPeriod) =>
      '${periodStartLabel(startPeriod)}–${periodEndLabel(endPeriod)}';

  Map<String, dynamic> toJson() => {
    'morning_period_count': morningPeriodCount,
    'afternoon_period_count': afternoonPeriodCount,
    'evening_period_count': eveningPeriodCount,
    'morning_start_minutes': morningStartMinutes,
    'afternoon_start_minutes': afternoonStartMinutes,
    'evening_start_minutes': eveningStartMinutes,
    'period_duration_minutes': periodDurationMinutes,
    'break_duration_minutes': breakDurationMinutes,
  };

  factory ScheduleSettings.fromJson(Map<String, dynamic> json) {
    int number(String key, int fallback) =>
        (json[key] as num?)?.toInt() ?? fallback;
    final legacyStart = number('first_period_start_minutes', 8 * 60);
    return ScheduleSettings(
      morningPeriodCount: number('morning_period_count', 4).clamp(0, 8),
      afternoonPeriodCount: number('afternoon_period_count', 4).clamp(0, 8),
      eveningPeriodCount: number('evening_period_count', 4).clamp(0, 8),
      morningStartMinutes: number(
        'morning_start_minutes',
        legacyStart,
      ).clamp(0, 23 * 60 + 59),
      afternoonStartMinutes: number(
        'afternoon_start_minutes',
        14 * 60,
      ).clamp(0, 23 * 60 + 59),
      eveningStartMinutes: number(
        'evening_start_minutes',
        19 * 60,
      ).clamp(0, 23 * 60 + 59),
      periodDurationMinutes: number(
        'period_duration_minutes',
        45,
      ).clamp(20, 180),
      breakDurationMinutes: number('break_duration_minutes', 10).clamp(0, 120),
    );
  }
}

String formatClockMinutes(int totalMinutes) {
  final normalized = totalMinutes % (24 * 60);
  final hours = normalized ~/ 60;
  final minutes = normalized % 60;
  return '${hours.toString().padLeft(2, '0')}:'
      '${minutes.toString().padLeft(2, '0')}';
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

class LearningCourseSummary {
  const LearningCourseSummary({
    required this.name,
    required this.totalPoints,
    required this.evaluatedPoints,
    required this.weakPoints,
    required this.reviewPoints,
    this.canonicalCourse,
    this.supported = true,
    this.source = 'manual',
    this.averageMastery,
  });

  final String name;
  final int totalPoints;
  final int evaluatedPoints;
  final int weakPoints;
  final int reviewPoints;
  final String? canonicalCourse;
  final bool supported;
  final String source;
  final double? averageMastery;

  factory LearningCourseSummary.fromJson(Map<String, dynamic> json) =>
      LearningCourseSummary(
        name: json['name']?.toString() ?? '',
        totalPoints: (json['total_points'] as num?)?.toInt() ?? 0,
        evaluatedPoints: (json['evaluated_points'] as num?)?.toInt() ?? 0,
        weakPoints: (json['weak_points'] as num?)?.toInt() ?? 0,
        reviewPoints: (json['review_points'] as num?)?.toInt() ?? 0,
        canonicalCourse: json['canonical_course']?.toString(),
        supported: json['supported'] as bool? ?? true,
        source: json['source']?.toString() ?? 'manual',
        averageMastery: (json['average_mastery'] as num?)?.toDouble(),
      );
}

class LearningCourseCatalogItem {
  const LearningCourseCatalogItem({required this.name, required this.added});

  final String name;
  final bool added;

  factory LearningCourseCatalogItem.fromJson(Map<String, dynamic> json) =>
      LearningCourseCatalogItem(
        name: json['name']?.toString() ?? '',
        added: json['added'] as bool? ?? false,
      );
}

class KnowledgeMapNode {
  const KnowledgeMapNode({
    required this.id,
    required this.name,
    required this.course,
    required this.category,
    required this.weight,
    required this.external,
    required this.hasRecord,
    required this.status,
    required this.needsReview,
    required this.practiceCount,
    required this.evidenceCount,
    required this.weakPrerequisiteCount,
    required this.level,
    this.masteryLevel,
    this.retention,
    this.evidenceConfidence,
  });

  final String id;
  final String name;
  final String course;
  final String category;
  final double weight;
  final bool external;
  final bool hasRecord;
  final double? masteryLevel;
  final String status;
  final double? retention;
  final double? evidenceConfidence;
  final bool needsReview;
  final int practiceCount;
  final int evidenceCount;
  final int weakPrerequisiteCount;
  final int level;

  factory KnowledgeMapNode.fromJson(Map<String, dynamic> json) =>
      KnowledgeMapNode(
        id: json['id']?.toString() ?? '',
        name: json['name']?.toString() ?? '',
        course: json['course']?.toString() ?? '',
        category: json['category']?.toString() ?? 'general',
        weight: (json['weight'] as num?)?.toDouble() ?? 0,
        external: json['external'] as bool? ?? false,
        hasRecord: json['has_record'] as bool? ?? false,
        masteryLevel: (json['mastery_level'] as num?)?.toDouble(),
        status: json['status']?.toString() ?? 'unseen',
        retention: (json['retention'] as num?)?.toDouble(),
        evidenceConfidence: (json['evidence_confidence'] as num?)?.toDouble(),
        needsReview: json['needs_review'] as bool? ?? false,
        practiceCount: (json['practice_count'] as num?)?.toInt() ?? 0,
        evidenceCount: (json['evidence_count'] as num?)?.toInt() ?? 0,
        weakPrerequisiteCount:
            (json['weak_prerequisite_count'] as num?)?.toInt() ?? 0,
        level: (json['level'] as num?)?.toInt() ?? 0,
      );
}

class KnowledgeMapEdge {
  const KnowledgeMapEdge({
    required this.from,
    required this.to,
    required this.type,
  });

  final String from;
  final String to;
  final String type;

  factory KnowledgeMapEdge.fromJson(Map<String, dynamic> json) =>
      KnowledgeMapEdge(
        from: json['from']?.toString() ?? '',
        to: json['to']?.toString() ?? '',
        type: json['type']?.toString() ?? 'prerequisite',
      );
}

class KnowledgeMapData {
  const KnowledgeMapData({
    required this.course,
    required this.nodes,
    required this.edges,
  });

  final String course;
  final List<KnowledgeMapNode> nodes;
  final List<KnowledgeMapEdge> edges;

  factory KnowledgeMapData.fromJson(Map<String, dynamic> json) =>
      KnowledgeMapData(
        course: json['course']?.toString() ?? '',
        nodes: (json['nodes'] as List? ?? const [])
            .whereType<Map>()
            .map(
              (item) =>
                  KnowledgeMapNode.fromJson(Map<String, dynamic>.from(item)),
            )
            .toList(),
        edges: (json['edges'] as List? ?? const [])
            .whereType<Map>()
            .map(
              (item) =>
                  KnowledgeMapEdge.fromJson(Map<String, dynamic>.from(item)),
            )
            .toList(),
      );
}

class KnowledgePointDetail {
  const KnowledgePointDetail({required this.raw});

  final Map<String, dynamic> raw;
  Map<String, dynamic> get point =>
      Map<String, dynamic>.from(raw['point'] as Map? ?? const {});
  Map<String, dynamic> get state =>
      Map<String, dynamic>.from(raw['state'] as Map? ?? const {});
  Map<String, dynamic> get evidence =>
      Map<String, dynamic>.from(raw['evidence_summary'] as Map? ?? const {});
  List<Map<String, dynamic>> get weakPrerequisites =>
      (raw['weak_prerequisites'] as List? ?? const [])
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList();
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
