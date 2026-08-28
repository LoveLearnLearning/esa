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
    this.displayName = '',
    this.major = 'cs',
    this.grade = '',
    this.currentWeek = 1,
    this.totalWeeks = 16,
    this.profileEnabled = false,
  });

  final String displayName;
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
      displayName: value('display_name') as String? ?? '',
      major: value('major') as String? ?? 'cs',
      grade: value('grade') as String? ?? '',
      currentWeek: (value('current_week') as num?)?.toInt() ?? 1,
      totalWeeks: (value('total_weeks') as num?)?.toInt() ?? 18,
      profileEnabled: value('profile_enabled') as bool? ?? true,
    );
  }
}

class UserStats {
  const UserStats({
    this.conversationCount = 0,
    this.pinnedCount = 0,
    this.learningStreakDays = 0,
  });

  final int conversationCount;
  final int pinnedCount;
  final int learningStreakDays;

  factory UserStats.fromJson(Map<String, dynamic> json) => UserStats(
    conversationCount: (json['conversation_count'] as num?)?.toInt() ?? 0,
    pinnedCount: (json['pinned_count'] as num?)?.toInt() ?? 0,
    learningStreakDays: (json['learning_streak_days'] as num?)?.toInt() ?? 0,
  );
}

class PlannerTodo {
  const PlannerTodo({
    required this.id,
    required this.title,
    required this.createdAt,
    required this.updatedAt,
    this.dueAt,
    this.done = false,
  });

  final String id;
  final String title;
  final DateTime createdAt;
  final DateTime updatedAt;
  final DateTime? dueAt;
  final bool done;

  factory PlannerTodo.fromJson(Map<String, dynamic> json) => PlannerTodo(
    id: json['todo_id']?.toString() ?? '',
    title: json['title']?.toString() ?? '',
    dueAt: DateTime.tryParse(json['due_at']?.toString() ?? '')?.toLocal(),
    done: json['done'] as bool? ?? false,
    createdAt:
        DateTime.tryParse(json['created_at']?.toString() ?? '')?.toLocal() ??
        DateTime.now(),
    updatedAt:
        DateTime.tryParse(json['updated_at']?.toString() ?? '')?.toLocal() ??
        DateTime.now(),
  );
}

class PlannerGoal {
  const PlannerGoal({
    required this.id,
    required this.title,
    required this.createdAt,
    required this.updatedAt,
    this.description = '',
    this.targetAt,
    this.progress = 0,
  });

  final String id;
  final String title;
  final String description;
  final DateTime createdAt;
  final DateTime updatedAt;
  final DateTime? targetAt;
  final int progress;

  factory PlannerGoal.fromJson(Map<String, dynamic> json) => PlannerGoal(
    id: json['goal_id']?.toString() ?? '',
    title: json['title']?.toString() ?? '',
    description: json['description']?.toString() ?? '',
    targetAt: DateTime.tryParse(json['target_at']?.toString() ?? '')?.toLocal(),
    progress: ((json['progress'] as num?)?.toInt() ?? 0).clamp(0, 100),
    createdAt:
        DateTime.tryParse(json['created_at']?.toString() ?? '')?.toLocal() ??
        DateTime.now(),
    updatedAt:
        DateTime.tryParse(json['updated_at']?.toString() ?? '')?.toLocal() ??
        DateTime.now(),
  );
}

class PlannerSnapshot {
  const PlannerSnapshot({this.todos = const [], this.goals = const []});

  final List<PlannerTodo> todos;
  final List<PlannerGoal> goals;

  factory PlannerSnapshot.fromJson(
    Map<String, dynamic> json,
  ) => PlannerSnapshot(
    todos: (json['todos'] as List? ?? const [])
        .whereType<Map>()
        .map((item) => PlannerTodo.fromJson(Map<String, dynamic>.from(item)))
        .toList(),
    goals: (json['goals'] as List? ?? const [])
        .whereType<Map>()
        .map((item) => PlannerGoal.fromJson(Map<String, dynamic>.from(item)))
        .toList(),
  );
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
    this.termStartDate = '',
  });

  final int morningPeriodCount;
  final int afternoonPeriodCount;
  final int eveningPeriodCount;
  final int morningStartMinutes;
  final int afternoonStartMinutes;
  final int eveningStartMinutes;
  final int periodDurationMinutes;
  final int breakDurationMinutes;
  final String termStartDate;

  int get totalPeriods =>
      morningPeriodCount + afternoonPeriodCount + eveningPeriodCount;

  DateTime? get parsedTermStartDate => DateTime.tryParse(termStartDate);

  int weekForDate(DateTime date) {
    final start = parsedTermStartDate;
    if (start == null) return 1;
    final current = DateTime(date.year, date.month, date.day);
    final firstDay = DateTime(start.year, start.month, start.day);
    final elapsedDays = current.difference(firstDay).inDays;
    return elapsedDays < 0 ? 1 : elapsedDays ~/ 7 + 1;
  }

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
    'term_start_date': termStartDate,
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
      termStartDate: json['term_start_date']?.toString() ?? '',
    );
  }
}

class ScheduleTable {
  const ScheduleTable({
    required this.id,
    required this.name,
    required this.isActive,
  });

  final String id;
  final String name;
  final bool isActive;

  factory ScheduleTable.fromJson(Map<String, dynamic> json) => ScheduleTable(
    id: json['id'] as String? ?? '',
    name: json['name'] as String? ?? '',
    isActive: json['is_active'] as bool? ?? false,
  );
}

class ScheduleSnapshot {
  const ScheduleSnapshot({
    required this.courses,
    required this.settings,
    this.tables = const [],
    this.activeTableId = '',
  });

  final List<ScheduleCourse> courses;
  final ScheduleSettings settings;
  final List<ScheduleTable> tables;
  final String activeTableId;

  factory ScheduleSnapshot.fromJson(
    Map<String, dynamic> json,
  ) => ScheduleSnapshot(
    courses: (json['courses'] as List? ?? const [])
        .whereType<Map>()
        .map((item) => ScheduleCourse.fromJson(Map<String, dynamic>.from(item)))
        .toList(),
    settings: ScheduleSettings.fromJson(
      Map<String, dynamic>.from(json['settings'] as Map? ?? const {}),
    ),
    tables: (json['tables'] as List? ?? const [])
        .whereType<Map>()
        .map((item) => ScheduleTable.fromJson(Map<String, dynamic>.from(item)))
        .toList(),
    activeTableId: json['active_table_id'] as String? ?? '',
  );
}

/// POST /me/schedule/import 的结果：成功导入的课程 + 因时间冲突被跳过的条数
class ScheduleImportResult {
  const ScheduleImportResult({
    required this.courses,
    required this.skippedCount,
    this.importedCount,
    this.warnings = const [],
    this.documentPipeline = 'legacy',
    this.documentId,
  });

  final List<ScheduleCourse> courses;
  final int skippedCount;
  final int? importedCount;
  final List<String> warnings;
  final String documentPipeline;
  final String? documentId;
}

class DocumentAttachment {
  const DocumentAttachment({
    required this.id,
    required this.filename,
    required this.mode,
    required this.tokenCount,
    required this.elementCount,
    required this.pageCount,
    required this.validationStatus,
    required this.qualityIssueCount,
    this.mediaType = 'application/octet-stream',
    this.sizeBytes = 0,
  });

  final String id;
  final String filename;
  final String mode;
  final int tokenCount;
  final int elementCount;
  final int pageCount;
  final String validationStatus;
  final int qualityIssueCount;
  final String mediaType;
  final int sizeBytes;

  String get extension {
    final index = filename.lastIndexOf('.');
    return index < 0 ? '' : filename.substring(index + 1).toLowerCase();
  }

  String get modeLabel => switch (mode) {
    'pending' => '已上传 · 发送后按需解析',
    'rag' => 'DocIR · RAG',
    _ => 'DocIR · 全文',
  };

  factory DocumentAttachment.fromJson(Map<String, dynamic> json) =>
      DocumentAttachment(
        id: json['id']?.toString() ?? '',
        filename: json['filename']?.toString() ?? '附件',
        mode: json['mode']?.toString() ?? 'direct',
        tokenCount: (json['token_count'] as num?)?.toInt() ?? 0,
        elementCount: (json['element_count'] as num?)?.toInt() ?? 0,
        pageCount: (json['page_count'] as num?)?.toInt() ?? 0,
        validationStatus: json['validation_status']?.toString() ?? '',
        qualityIssueCount: (json['quality_issue_count'] as num?)?.toInt() ?? 0,
        mediaType: json['media_type']?.toString() ?? 'application/octet-stream',
        sizeBytes: (json['size_bytes'] as num?)?.toInt() ?? 0,
      );
}

enum KnowledgeBaseBuildStatus { idle, queued, building, ready, failed }

KnowledgeBaseBuildStatus knowledgeBaseBuildStatusFromString(String value) =>
    switch (value) {
      'queued' => KnowledgeBaseBuildStatus.queued,
      'building' ||
      'processing' ||
      'indexing' => KnowledgeBaseBuildStatus.building,
      'ready' => KnowledgeBaseBuildStatus.ready,
      'failed' => KnowledgeBaseBuildStatus.failed,
      _ => KnowledgeBaseBuildStatus.idle,
    };

class KnowledgeBaseFile {
  const KnowledgeBaseFile({
    required this.id,
    required this.filename,
    required this.mediaType,
    required this.sizeBytes,
    required this.status,
    required this.progress,
    required this.chunkCount,
    required this.indexCount,
    required this.uploadedAt,
    this.error,
  });

  final String id;
  final String filename;
  final String mediaType;
  final int sizeBytes;
  final KnowledgeBaseBuildStatus status;
  final double progress;
  final int chunkCount;
  final int indexCount;
  final DateTime? uploadedAt;
  final String? error;

  String get extension {
    final index = filename.lastIndexOf('.');
    return index < 0 ? '' : filename.substring(index + 1).toLowerCase();
  }

  DocumentAttachment get previewAttachment => DocumentAttachment(
    id: id,
    filename: filename,
    mode: status == KnowledgeBaseBuildStatus.ready ? 'rag' : 'pending',
    tokenCount: 0,
    elementCount: chunkCount,
    pageCount: 0,
    validationStatus: status.name,
    qualityIssueCount: 0,
    mediaType: mediaType,
    sizeBytes: sizeBytes,
  );

  factory KnowledgeBaseFile.fromJson(Map<String, dynamic> json) =>
      KnowledgeBaseFile(
        id: json['id']?.toString() ?? '',
        filename: json['filename']?.toString() ?? '未命名文件',
        mediaType: json['media_type']?.toString() ?? 'application/octet-stream',
        sizeBytes: (json['size_bytes'] as num?)?.toInt() ?? 0,
        status: knowledgeBaseBuildStatusFromString(
          json['status']?.toString() ?? '',
        ),
        progress: ((json['progress'] as num?)?.toDouble() ?? 0).clamp(0, 1),
        chunkCount: (json['chunk_count'] as num?)?.toInt() ?? 0,
        indexCount: (json['index_count'] as num?)?.toInt() ?? 0,
        uploadedAt: DateTime.tryParse(json['uploaded_at']?.toString() ?? ''),
        error: json['error']?.toString(),
      );
}

class PersonalKnowledgeBase {
  const PersonalKnowledgeBase({
    required this.fileCount,
    required this.chunkCount,
    required this.indexCount,
    required this.status,
    required this.progress,
    required this.files,
    this.updatedAt,
    this.error,
  });

  const PersonalKnowledgeBase.empty()
    : fileCount = 0,
      chunkCount = 0,
      indexCount = 0,
      status = KnowledgeBaseBuildStatus.idle,
      progress = 0,
      files = const [],
      updatedAt = null,
      error = null;

  final int fileCount;
  final int chunkCount;
  final int indexCount;
  final KnowledgeBaseBuildStatus status;
  final double progress;
  final List<KnowledgeBaseFile> files;
  final DateTime? updatedAt;
  final String? error;

  bool get isBuilding =>
      status == KnowledgeBaseBuildStatus.queued ||
      status == KnowledgeBaseBuildStatus.building;

  factory PersonalKnowledgeBase.fromJson(Map<String, dynamic> json) =>
      PersonalKnowledgeBase(
        fileCount: (json['file_count'] as num?)?.toInt() ?? 0,
        chunkCount: (json['chunk_count'] as num?)?.toInt() ?? 0,
        indexCount: (json['index_count'] as num?)?.toInt() ?? 0,
        status: knowledgeBaseBuildStatusFromString(
          json['status']?.toString() ?? '',
        ),
        progress: ((json['progress'] as num?)?.toDouble() ?? 0).clamp(0, 1),
        files: (json['files'] as List? ?? const [])
            .whereType<Map>()
            .map(
              (item) =>
                  KnowledgeBaseFile.fromJson(Map<String, dynamic>.from(item)),
            )
            .toList(),
        updatedAt: DateTime.tryParse(json['updated_at']?.toString() ?? ''),
        error: json['error']?.toString(),
      );
}

class PersonalKnowledgeBaseSummary {
  const PersonalKnowledgeBaseSummary({
    required this.id,
    required this.name,
    required this.fileCount,
    required this.chunkCount,
    required this.indexCount,
    required this.updatedAt,
  });

  final String id;
  final String name;
  final int fileCount;
  final int chunkCount;
  final int indexCount;
  final DateTime? updatedAt;

  factory PersonalKnowledgeBaseSummary.fromJson(Map<String, dynamic> json) =>
      PersonalKnowledgeBaseSummary(
        id: json['id']?.toString() ?? '',
        name: json['name']?.toString() ?? '未命名知识库',
        fileCount: (json['file_count'] as num?)?.toInt() ?? 0,
        chunkCount: (json['chunk_count'] as num?)?.toInt() ?? 0,
        indexCount: (json['index_count'] as num?)?.toInt() ?? 0,
        updatedAt: DateTime.tryParse(json['updated_at']?.toString() ?? ''),
      );
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
    this.nodeType = 'knowledge_point',
    this.masteryLevel,
    this.retention,
    this.evidenceConfidence,
  });

  final String id;
  final String nodeType;
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

  bool get isCourse => nodeType == 'course';

  factory KnowledgeMapNode.fromJson(Map<String, dynamic> json) =>
      KnowledgeMapNode(
        id: json['id']?.toString() ?? '',
        nodeType: json['node_type']?.toString() ?? 'knowledge_point',
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

  factory KnowledgeMapData.fromJson(Map<String, dynamic> json) {
    final course = json['course']?.toString() ?? '';
    final nodes = (json['nodes'] as List? ?? const [])
        .whereType<Map>()
        .map(
          (item) => KnowledgeMapNode.fromJson(Map<String, dynamic>.from(item)),
        )
        .toList();
    final edges = (json['edges'] as List? ?? const [])
        .whereType<Map>()
        .map(
          (item) => KnowledgeMapEdge.fromJson(Map<String, dynamic>.from(item)),
        )
        .toList();
    if (course.isEmpty || nodes.isEmpty || nodes.any((node) => node.isCourse)) {
      return KnowledgeMapData(course: course, nodes: nodes, edges: edges);
    }

    final nodeIds = nodes.map((node) => node.id).toSet();
    final incoming = {for (final id in nodeIds) id: 0};
    final adjacency = {for (final id in nodeIds) id: <String>{}};
    for (final edge in edges) {
      if (!nodeIds.contains(edge.from) || !nodeIds.contains(edge.to)) continue;
      incoming[edge.to] = incoming[edge.to]! + 1;
      adjacency[edge.from]!.add(edge.to);
      adjacency[edge.to]!.add(edge.from);
    }
    final roots = <String>[];
    final remaining = {...nodeIds};
    while (remaining.isNotEmpty) {
      final start = remaining.reduce((a, b) => a.compareTo(b) <= 0 ? a : b);
      final component = <String>{start};
      final queue = <String>[start];
      for (var index = 0; index < queue.length; index++) {
        for (final neighbor in adjacency[queue[index]]!) {
          if (component.add(neighbor)) queue.add(neighbor);
        }
      }
      remaining.removeAll(component);
      final componentRoots = component.where((id) => incoming[id] == 0).toList()
        ..sort();
      roots.add(
        componentRoots.isEmpty
            ? component.reduce((a, b) => a.compareTo(b) <= 0 ? a : b)
            : componentRoots.first,
      );
      if (componentRoots.length > 1) roots.addAll(componentRoots.skip(1));
    }

    final courseNodeId = '__course__:$course';
    return KnowledgeMapData(
      course: course,
      nodes: [
        KnowledgeMapNode(
          id: courseNodeId,
          nodeType: 'course',
          name: course,
          course: course,
          category: 'course',
          weight: 0,
          external: false,
          hasRecord: false,
          status: 'course',
          needsReview: false,
          practiceCount: 0,
          evidenceCount: 0,
          weakPrerequisiteCount: 0,
          level: -1,
        ),
        ...nodes,
      ],
      edges: [
        for (final root in roots)
          KnowledgeMapEdge(from: courseNodeId, to: root, type: 'course_root'),
        ...edges,
      ],
    );
  }
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
    required this.id,
    required this.key,
    required this.content,
    required this.category,
    this.scopeType = 'global',
    this.workspaceType,
    this.status = 'active',
    this.revision = 1,
  });

  final String id;
  final String key;
  final String content;
  final String category;
  final String scopeType;
  final String? workspaceType;
  final String status;
  final int revision;

  factory CoreMemoryItem.fromJson(Map<String, dynamic> json) => CoreMemoryItem(
    id: json['memory_id'] as String? ?? json['memory_key'] as String? ?? '',
    key: json['memory_key'] as String? ?? '',
    content: json['content'] as String? ?? '',
    category: json['category'] as String? ?? 'general',
    scopeType: json['scope_type'] as String? ?? 'global',
    workspaceType: json['workspace_type'] as String?,
    status: json['status'] as String? ?? 'active',
    revision: json['revision'] as int? ?? 1,
  );
}

class MemoryCandidateItem {
  const MemoryCandidateItem({
    required this.id,
    required this.key,
    required this.content,
    required this.category,
    required this.scopeType,
    this.workspaceType,
  });
  final String id;
  final String key;
  final String content;
  final String category;
  final String scopeType;
  final String? workspaceType;

  factory MemoryCandidateItem.fromJson(Map<String, dynamic> json) =>
      MemoryCandidateItem(
        id: json['candidate_id'] as String? ?? '',
        key: json['memory_key'] as String? ?? '',
        content: json['proposed_content'] as String? ?? '',
        category: json['category'] as String? ?? 'general',
        scopeType: json['scope_type'] as String? ?? 'global',
        workspaceType: json['workspace_type'] as String?,
      );
}

class ResearchProjectProfile {
  const ResearchProjectProfile({
    required this.instructions,
    required this.revision,
  });
  final String instructions;
  final int revision;
  factory ResearchProjectProfile.fromJson(Map<String, dynamic> json) =>
      ResearchProjectProfile(
        instructions: json['agent_instructions'] as String? ?? '',
        revision: json['revision'] as int? ?? 0,
      );
}

class AgentActionItem {
  const AgentActionItem({
    required this.id,
    required this.type,
    required this.status,
    required this.workspaceType,
    required this.arguments,
    required this.resourceSnapshot,
    required this.createdAt,
    required this.expiresAt,
    this.error,
  });

  final String id;
  final String type;
  final String status;
  final String workspaceType;
  final Map<String, dynamic> arguments;
  final Map<String, dynamic> resourceSnapshot;
  final DateTime? createdAt;
  final DateTime? expiresAt;
  final String? error;

  factory AgentActionItem.fromJson(Map<String, dynamic> json) =>
      AgentActionItem(
        id: json['action_id']?.toString() ?? '',
        type: json['action_type']?.toString() ?? '',
        status: json['status']?.toString() ?? 'pending',
        workspaceType: json['workspace_type']?.toString() ?? '',
        arguments: json['arguments'] is Map
            ? Map<String, dynamic>.from(json['arguments'] as Map)
            : const {},
        resourceSnapshot: json['resource_snapshot'] is Map
            ? Map<String, dynamic>.from(json['resource_snapshot'] as Map)
            : const {},
        createdAt: DateTime.tryParse(json['created_at']?.toString() ?? ''),
        expiresAt: DateTime.tryParse(json['expires_at']?.toString() ?? ''),
        error: json['error']?.toString(),
      );
}

enum MessageRole { user, assistant, tool }

/// A source emitted by a retrieval tool and attached to one assistant reply.
class SourceCitation {
  const SourceCitation({
    required this.index,
    required this.label,
    this.filename,
    this.fileId,
    this.knowledgeBaseId,
    this.documentId,
    this.previewUrl,
    this.page,
    this.section,
    this.sourceType = 'public',
    this.highlightText,
    this.originalText,
  });

  final int index;
  final String label;
  final String? filename;
  final String? fileId;
  final String? knowledgeBaseId;
  final String? documentId;
  final String? previewUrl;
  final int? page;
  final String? section;
  final String sourceType;
  final String? highlightText;
  final String? originalText;

  String get locationLabel {
    // Public knowledge-base citations do not have a local file to open. Keep
    // their source label and append any structured location metadata.
    if (filename == null || filename!.trim().isEmpty) {
      final parts = <String>[label.trim()];
      if (page != null && page! > 0) parts.add('第$page页');
      if (section != null && section!.trim().isNotEmpty) {
        parts.add(section!.trim());
      }
      return parts.where((part) => part.isNotEmpty).join(' · ');
    }
    final parts = <String>[];
    parts.add(filename!.trim());
    if (page != null && page! > 0) parts.add('第$page页');
    if (section != null && section!.trim().isNotEmpty) {
      parts.add(section!.trim());
    }
    return parts.join(' · ');
  }

  bool get canOpen =>
      originalText?.trim().isNotEmpty == true ||
      (filename != null && filename!.trim().isNotEmpty) ||
      (fileId != null && fileId!.trim().isNotEmpty) ||
      (previewUrl != null && previewUrl!.trim().isNotEmpty);
}

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
    this.toolRunning = false,
    this.attachments = const [],
  });

  String id;
  final MessageRole role;
  String text;
  final String? name; // 仅 tool 消息有 工具名
  final String? createdAt;
  bool typing; // 等待后端回复时显示光标
  final bool markdown; // 仅前端使用：用户是否通过 Markdown 模式发送
  String reasoning; // 后端可选返回：模型思考内容
  bool toolRunning; // 工具已开始调用但结果尚未返回
  final List<DocumentAttachment> attachments;

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
      toolRunning: false,
      attachments: (j['attachments'] as List? ?? const [])
          .whereType<Map>()
          .map(
            (item) =>
                DocumentAttachment.fromJson(Map<String, dynamic>.from(item)),
          )
          .toList(),
    );
  }

  static ChatMessage user(
    String text, {
    bool markdown = false,
    List<DocumentAttachment> attachments = const [],
  }) => ChatMessage(
    id: _nextId(),
    role: MessageRole.user,
    text: text,
    markdown: markdown,
    attachments: attachments,
  );

  static ChatMessage typingPlaceholder() =>
      ChatMessage(id: _nextId(), role: MessageRole.assistant, typing: true);
}

/// 一个历史对话 对应 /conversations 的元素
enum WorkspaceType {
  learning,
  teaching,
  research;

  String get wireName => name;
  String get label => switch (this) {
    WorkspaceType.learning => '学习空间',
    WorkspaceType.teaching => '教学空间',
    WorkspaceType.research => '科研空间',
  };

  static WorkspaceType fromWire(String? value) => switch (value) {
    'teaching' => WorkspaceType.teaching,
    'research' => WorkspaceType.research,
    _ => WorkspaceType.learning,
  };
}

enum KnowledgeSource {
  personal,
  public;

  String get wireName => name;

  String get label => switch (this) {
    KnowledgeSource.personal => '个人知识库',
    KnowledgeSource.public => '公共知识库',
  };
}

class WorkspaceDescriptor {
  const WorkspaceDescriptor({
    required this.type,
    required this.name,
    required this.description,
    required this.capabilities,
  });

  final WorkspaceType type;
  final String name;
  final String description;
  final List<String> capabilities;

  factory WorkspaceDescriptor.fromJson(Map<String, dynamic> json) =>
      WorkspaceDescriptor(
        type: WorkspaceType.fromWire(json['type'] as String?),
        name: json['name'] as String? ?? '',
        description: json['description'] as String? ?? '',
        capabilities: (json['capabilities'] as List? ?? const [])
            .whereType<String>()
            .toList(),
      );
}

class WorkspaceManifest {
  const WorkspaceManifest({
    required this.accountRole,
    required this.defaultWorkspace,
    required this.workspaces,
  });

  final String accountRole;
  final WorkspaceType defaultWorkspace;
  final List<WorkspaceDescriptor> workspaces;

  factory WorkspaceManifest.fromJson(Map<String, dynamic> json) =>
      WorkspaceManifest(
        accountRole: json['account_role'] as String? ?? 'student',
        defaultWorkspace: WorkspaceType.fromWire(
          json['default_workspace'] as String?,
        ),
        workspaces: (json['workspaces'] as List? ?? const [])
            .whereType<Map<String, dynamic>>()
            .map(WorkspaceDescriptor.fromJson)
            .toList(),
      );
}

class ResearchProject {
  const ResearchProject({
    required this.id,
    required this.name,
    required this.description,
    required this.status,
    required this.updatedAt,
  });

  final String id;
  final String name;
  final String description;
  final String status;
  final DateTime updatedAt;

  factory ResearchProject.fromJson(Map<String, dynamic> json) =>
      ResearchProject(
        id: json['project_id'] as String,
        name: json['name'] as String? ?? '',
        description: json['description'] as String? ?? '',
        status: json['status'] as String? ?? 'active',
        updatedAt:
            DateTime.tryParse(json['updated_at'] as String? ?? '')?.toLocal() ??
            DateTime.now(),
      );

  ResearchProject copyWith({
    String? name,
    String? description,
    String? status,
    DateTime? updatedAt,
  }) => ResearchProject(
    id: id,
    name: name ?? this.name,
    description: description ?? this.description,
    status: status ?? this.status,
    updatedAt: updatedAt ?? this.updatedAt,
  );
}

class FrontierTrackingJob {
  const FrontierTrackingJob({
    required this.id,
    required this.query,
    required this.status,
    this.result,
    this.error,
  });

  final String id;
  final String query;
  final String status;
  final Map<String, dynamic>? result;
  final String? error;

  bool get isFinished => status == 'succeeded' || status == 'failed';

  factory FrontierTrackingJob.fromJson(Map<String, dynamic> json) =>
      FrontierTrackingJob(
        id: json['job_id']?.toString() ?? '',
        query: json['query']?.toString() ?? '',
        status: json['status']?.toString() ?? 'queued',
        result: json['result'] is Map
            ? Map<String, dynamic>.from(json['result'] as Map)
            : null,
        error: json['error']?.toString(),
      );
}

class ResearchDocument {
  const ResearchDocument({
    required this.id,
    required this.title,
    required this.type,
    required this.content,
    required this.version,
  });

  final String id;
  final String title;
  final String type;
  final String content;
  final int version;

  factory ResearchDocument.fromJson(Map<String, dynamic> json) =>
      ResearchDocument(
        id: json['document_id']?.toString() ?? '',
        title: json['title']?.toString() ?? '',
        type: json['document_type']?.toString() ?? 'notes',
        content: json['content']?.toString() ?? '',
        version: (json['version'] as num?)?.toInt() ?? 1,
      );
}

class ResearchWritingJob {
  const ResearchWritingJob({
    required this.id,
    required this.documentId,
    required this.status,
    this.error,
  });

  final String id;
  final String documentId;
  final String status;
  final String? error;

  bool get isFinished => status == 'succeeded' || status == 'failed';

  factory ResearchWritingJob.fromJson(Map<String, dynamic> json) =>
      ResearchWritingJob(
        id: json['job_id']?.toString() ?? '',
        documentId: json['document_id']?.toString() ?? '',
        status: json['status']?.toString() ?? 'queued',
        error: json['error']?.toString(),
      );
}

class ResearchDataset {
  const ResearchDataset({
    required this.id,
    required this.name,
    required this.filename,
    required this.rowCount,
    required this.columnCount,
    required this.profile,
  });

  final String id;
  final String name;
  final String filename;
  final int rowCount;
  final int columnCount;
  final Map<String, dynamic> profile;

  factory ResearchDataset.fromJson(Map<String, dynamic> json) =>
      ResearchDataset(
        id: json['dataset_id']?.toString() ?? '',
        name: json['name']?.toString() ?? '',
        filename: json['original_filename']?.toString() ?? '',
        rowCount: (json['row_count'] as num?)?.toInt() ?? 0,
        columnCount: (json['column_count'] as num?)?.toInt() ?? 0,
        profile: json['profile'] is Map
            ? Map<String, dynamic>.from(json['profile'] as Map)
            : const {},
      );
}

class ResearchAnalysisJob {
  const ResearchAnalysisJob({
    required this.id,
    required this.datasetId,
    required this.type,
    required this.status,
    this.result,
    this.error,
  });

  final String id;
  final String datasetId;
  final String type;
  final String status;
  final Map<String, dynamic>? result;
  final String? error;

  bool get isFinished => status == 'succeeded' || status == 'failed';

  factory ResearchAnalysisJob.fromJson(Map<String, dynamic> json) =>
      ResearchAnalysisJob(
        id: json['job_id']?.toString() ?? '',
        datasetId: json['dataset_id']?.toString() ?? '',
        type: json['analysis_type']?.toString() ?? 'descriptive',
        status: json['status']?.toString() ?? 'queued',
        result: json['result'] is Map
            ? Map<String, dynamic>.from(json['result'] as Map)
            : null,
        error: json['error']?.toString(),
      );
}

class ChatConversation {
  ChatConversation({
    required this.id,
    required this.title,
    required this.updatedAt,
    this.pinned = false,
    this.workspaceType = WorkspaceType.learning,
    this.researchProjectId,
    this.classId,
    this.className,
    this.assignmentId,
    this.assignmentTitle,
    this.groupId,
  });

  final String id;
  String title;
  DateTime updatedAt;
  final WorkspaceType workspaceType;
  final String? researchProjectId;
  final String? classId;
  final String? className;
  final String? assignmentId;
  final String? assignmentTitle;
  String? groupId;
  bool pinned;

  factory ChatConversation.fromJson(Map<String, dynamic> j) {
    final binding = j['classroom_binding'] is Map
        ? Map<String, dynamic>.from(j['classroom_binding'] as Map)
        : const <String, dynamic>{};
    return ChatConversation(
      id: j['conversation_id'] as String,
      title: (j['title'] as String?) ?? '新对话',
      updatedAt:
          DateTime.tryParse(j['updated_at'] as String? ?? '')?.toLocal() ??
          DateTime.now(),
      workspaceType: WorkspaceType.fromWire(j['workspace_type'] as String?),
      researchProjectId: j['research_project_id'] as String?,
      classId: binding['class_id']?.toString(),
      className: binding['class_name']?.toString(),
      assignmentId: binding['assignment_id']?.toString(),
      assignmentTitle: binding['assignment_title']?.toString(),
      groupId: j['group_id'] as String?,
      pinned: j['pinned'] as bool? ?? false,
    );
  }
}

/// 用于区分“未提供字段”和“显式传 null”的分组更新哨兵值。
class GroupFieldUnset {
  const GroupFieldUnset();
}

const groupFieldUnset = GroupFieldUnset();

class ChatGroup {
  const ChatGroup({
    required this.id,
    required this.userId,
    required this.name,
    required this.description,
    required this.customInstruction,
    required this.conversationCount,
    required this.createdAt,
    required this.updatedAt,
    this.style,
    this.tone,
    this.projectId,
    this.pinned = false,
    this.sortOrder = 0,
  });

  final String id;
  final String userId;
  final String name;
  final String description;
  final String customInstruction;
  final String? style;
  final String? tone;
  final String? projectId;
  final bool pinned;
  final int sortOrder;
  final int conversationCount;
  final DateTime createdAt;
  final DateTime updatedAt;

  factory ChatGroup.fromJson(Map<String, dynamic> json) => ChatGroup(
    id: json['group_id'] as String? ?? '',
    userId: json['user_id'] as String? ?? '',
    name: json['name'] as String? ?? '',
    description: json['description'] as String? ?? '',
    customInstruction: json['custom_instruction'] as String? ?? '',
    style: json['style'] as String?,
    tone: json['tone'] as String?,
    projectId: json['project_id'] as String?,
    pinned: json['pinned'] as bool? ?? false,
    sortOrder: (json['sort_order'] as num?)?.toInt() ?? 0,
    conversationCount: (json['conversation_count'] as num?)?.toInt() ?? 0,
    createdAt:
        DateTime.tryParse(json['created_at'] as String? ?? '')?.toLocal() ??
        DateTime.now(),
    updatedAt:
        DateTime.tryParse(json['updated_at'] as String? ?? '')?.toLocal() ??
        DateTime.now(),
  );
}

/// Teaching API models. The backend uses snake_case identifiers while the
/// Flutter pages use small typed view models for the classroom workflow.
class TeachingClass {
  const TeachingClass({
    required this.id,
    required this.name,
    required this.course,
    this.term = '',
    this.description = '',
    this.status = 'active',
    this.studentCount = 0,
    this.openAssignmentCount = 0,
    this.membershipStatus,
    this.membershipId,
    this.teacherUsername,
  });

  final String id;
  final String name;
  final String course;
  final String term;
  final String description;
  final String status;
  final int studentCount;
  final int openAssignmentCount;
  final String? membershipStatus;
  final String? membershipId;
  final String? teacherUsername;

  factory TeachingClass.fromJson(Map<String, dynamic> json) => TeachingClass(
    id: (json['class_id'] ?? json['id'])?.toString() ?? '',
    name: json['name']?.toString() ?? '',
    course: (json['canonical_course'] ?? json['course'])?.toString() ?? '',
    term: json['term']?.toString() ?? '',
    description: json['description']?.toString() ?? '',
    status: json['status']?.toString() ?? 'active',
    studentCount: (json['student_count'] as num?)?.toInt() ?? 0,
    openAssignmentCount: (json['open_assignment_count'] as num?)?.toInt() ?? 0,
    membershipStatus: json['membership_status']?.toString(),
    membershipId: json['membership_id']?.toString(),
    teacherUsername: json['teacher_username']?.toString(),
  );
}

class TeachingQuestion {
  const TeachingQuestion({
    required this.id,
    required this.prompt,
    required this.maxPoints,
    this.questionType = 'short_answer',
    this.rubric = '',
    this.referenceAnswer = '',
    this.kpId,
  });

  final String id;
  final String prompt;
  final double maxPoints;
  final String questionType;
  final String rubric;
  final String referenceAnswer;
  final String? kpId;

  String get type => questionType;

  factory TeachingQuestion.fromJson(Map<String, dynamic> json) =>
      TeachingQuestion(
        id: (json['question_id'] ?? json['id'])?.toString() ?? '',
        prompt: json['prompt']?.toString() ?? '',
        maxPoints: (json['max_points'] as num?)?.toDouble() ?? 0,
        questionType: json['question_type']?.toString() ?? 'short_answer',
        rubric: json['rubric']?.toString() ?? '',
        referenceAnswer: json['reference_answer']?.toString() ?? '',
        kpId: json['kp_id']?.toString(),
      );
}

class TeachingAssignment {
  const TeachingAssignment({
    required this.id,
    required this.classId,
    required this.className,
    required this.course,
    required this.title,
    required this.instructions,
    required this.status,
    required this.totalPoints,
    required this.submittedCount,
    required this.studentCount,
    required this.questions,
    this.dueAt,
    this.submissionId,
    this.submissionStatus,
    this.analysisStatus,
    this.feedbackStatus,
    this.totalScore,
    this.submittedAt,
  });

  final String id;
  final String classId;
  final String className;
  final String course;
  final String title;
  final String instructions;
  final String status;
  final double totalPoints;
  final int submittedCount;
  final int studentCount;
  final List<TeachingQuestion> questions;
  final DateTime? dueAt;
  final String? submissionId;
  final String? submissionStatus;
  final String? analysisStatus;
  final String? feedbackStatus;
  final double? totalScore;
  final DateTime? submittedAt;

  factory TeachingAssignment.fromJson(Map<String, dynamic> json) {
    DateTime? date(String key) =>
        DateTime.tryParse(json[key]?.toString() ?? '');
    final rawQuestions = json['questions'];
    return TeachingAssignment(
      id: (json['assignment_id'] ?? json['id'])?.toString() ?? '',
      classId: json['class_id']?.toString() ?? '',
      className: json['class_name']?.toString() ?? '',
      course: (json['canonical_course'] ?? json['course'])?.toString() ?? '',
      title: json['title']?.toString() ?? '',
      instructions: json['instructions']?.toString() ?? '',
      status: json['status']?.toString() ?? 'draft',
      totalPoints: (json['total_points'] as num?)?.toDouble() ?? 0,
      submittedCount: (json['submitted_count'] as num?)?.toInt() ?? 0,
      studentCount: (json['student_count'] as num?)?.toInt() ?? 0,
      questions: rawQuestions is List
          ? rawQuestions
                .whereType<Map>()
                .map(
                  (item) => TeachingQuestion.fromJson(
                    Map<String, dynamic>.from(item),
                  ),
                )
                .toList()
          : const [],
      dueAt: date('due_at'),
      submissionId: json['submission_id']?.toString(),
      submissionStatus: json['submission_status']?.toString(),
      analysisStatus: json['analysis_status']?.toString(),
      feedbackStatus: json['feedback_status']?.toString(),
      totalScore: (json['total_score'] as num?)?.toDouble(),
      submittedAt: date('submitted_at'),
    );
  }
}

class TeachingAnswer {
  TeachingAnswer({
    required this.id,
    required this.questionId,
    required this.prompt,
    required this.answerText,
    required this.maxPoints,
    this.aiScore,
    this.finalScore,
    this.feedback = '',
    this.kpId,
    Map<String, dynamic>? raw,
  }) : raw = raw ?? <String, dynamic>{};

  final String id;
  final String questionId;
  final String prompt;
  final String answerText;
  final double maxPoints;
  final double? aiScore;
  final double? finalScore;
  final String feedback;
  final String? kpId;
  final Map<String, dynamic> raw;

  factory TeachingAnswer.fromJson(Map<String, dynamic> json) => TeachingAnswer(
    id: (json['answer_id'] ?? json['id'])?.toString() ?? '',
    questionId: json['question_id']?.toString() ?? '',
    prompt: json['prompt']?.toString() ?? '',
    answerText: json['answer_text']?.toString() ?? '',
    maxPoints: (json['max_points'] as num?)?.toDouble() ?? 0,
    aiScore: (json['ai_score'] as num?)?.toDouble(),
    finalScore: (json['final_score'] as num?)?.toDouble(),
    feedback: (json['final_feedback'] ?? json['ai_feedback'])?.toString() ?? '',
    kpId: (json['final_kp_id'] ?? json['ai_kp_id'] ?? json['kp_id'])
        ?.toString(),
    raw: Map<String, dynamic>.from(json),
  );
}

class TeachingSubmission {
  TeachingSubmission({
    required this.id,
    required this.studentUsername,
    required this.analysisStatus,
    required this.feedbackStatus,
    required this.answers,
    this.assignmentId = '',
    this.studentId = '',
    this.status = 'submitted',
    this.totalScore,
    this.submittedAt,
    this.version = 1,
  });

  final String id;
  final String assignmentId;
  final String studentId;
  final String studentUsername;
  final String status;
  final String analysisStatus;
  final String feedbackStatus;
  final double? totalScore;
  final DateTime? submittedAt;
  final int version;
  final List<TeachingAnswer> answers;

  factory TeachingSubmission.fromJson(Map<String, dynamic> json) {
    DateTime? date(String key) =>
        DateTime.tryParse(json[key]?.toString() ?? '');
    final rawAnswers = json['answers'];
    return TeachingSubmission(
      id: (json['submission_id'] ?? json['id'])?.toString() ?? '',
      assignmentId: json['assignment_id']?.toString() ?? '',
      studentId: json['student_id']?.toString() ?? '',
      studentUsername: json['student_username']?.toString() ?? '',
      status: json['status']?.toString() ?? 'submitted',
      analysisStatus: json['analysis_status']?.toString() ?? 'pending',
      feedbackStatus: json['feedback_status']?.toString() ?? 'unpublished',
      totalScore: (json['total_score'] as num?)?.toDouble(),
      submittedAt: date('submitted_at'),
      version: (json['version'] as num?)?.toInt() ?? 1,
      answers: rawAnswers is List
          ? rawAnswers
                .whereType<Map>()
                .map(
                  (item) =>
                      TeachingAnswer.fromJson(Map<String, dynamic>.from(item)),
                )
                .toList()
          : const [],
    );
  }
}
