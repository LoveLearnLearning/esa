// ESA 后端 REST 客户端 —— 按 API.md 对齐
// Base URL 可用 --dart-define=ESA_API_BASE=https://example.com/api 覆盖
// 认证：登录拿到 session_id 之后所有请求带 Authorization: Bearer <session_id>
//
// 当 config.dart 里 kOfflineMode == true 时 所有方法走本地假数据 完全不发网络请求

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';
import 'package:flutter/foundation.dart' show kIsWeb;

import '../config.dart';
import '../models/models.dart';

/// 后端返回的错误 statusCode + detail(取自 {"detail": ...})
class ApiException implements Exception {
  ApiException(this.statusCode, this.detail);
  final int statusCode;
  final String detail;

  bool get isUnauthorized => statusCode == 401;

  @override
  String toString() => detail;
}

/// `/messages/stream` 返回的一条 SSE 事件。
class ChatStreamEvent {
  const ChatStreamEvent(this.event, this.data);

  final String event;
  final Map<String, dynamic> data;
}

class AttachmentContent {
  const AttachmentContent({
    required this.bytes,
    required this.mediaType,
    required this.filename,
  });

  final Uint8List bytes;
  final String mediaType;
  final String filename;
}

class ApiClient {
  ApiClient({String? baseUrl})
    : baseUrl = _normalizeBaseUrl(baseUrl ?? _defaultBaseUrl);

  static const String _configuredBaseUrl = String.fromEnvironment(
    'ESA_API_BASE',
  );

  static String get _defaultBaseUrl {
    if (_configuredBaseUrl.isNotEmpty) return _configuredBaseUrl;
    // Web 始终同源访问 Nginx；原生客户端使用同一个 HTTPS 公网入口。
    return kIsWeb ? '/api' : 'https://esa.lovelearnlearning.cn/api';
  }

  static String _normalizeBaseUrl(String value) =>
      value.endsWith('/') ? value.substring(0, value.length - 1) : value;

  final String baseUrl;

  String? sessionId;
  String? userId;
  String? username;
  String? email;
  String accountRole = 'student';
  DateTime? sessionExpiresAt;

  bool get isLoggedIn => sessionId != null;

  Map<String, String> _headers({bool auth = false}) => {
    'Content-Type': 'application/json',
    if (auth && sessionId != null) 'Authorization': 'Bearer $sessionId',
  };

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  dynamic _decode(http.Response r) => jsonDecode(utf8.decode(r.bodyBytes));

  Never _fail(http.Response r) {
    String detail;
    try {
      final body = _decode(r);
      final d = body is Map ? body['detail'] : null;
      if (d is String) {
        detail = d;
      } else if (d is List) {
        detail = '请求参数不合法';
      } else {
        detail = '请求失败（${r.statusCode}）';
      }
    } catch (_) {
      detail = '请求失败（${r.statusCode}）';
    }
    throw ApiException(r.statusCode, detail);
  }

  // ---------- 认证 ----------
  Future<int> sendRegistrationCode(String email) async {
    if (kOfflineMode) return 60;
    final r = await http.post(
      _uri('/auth/email/send-code'),
      headers: _headers(),
      body: jsonEncode({'email': email}),
    );
    if (r.statusCode != 202) _fail(r);
    final data = _decode(r) as Map<String, dynamic>;
    return data['retry_after_seconds'] as int? ?? 60;
  }

  Future<void> register(
    String email,
    String verificationCode,
    String username,
    String password,
    String accountRole,
  ) async {
    if (kOfflineMode) return; // 离线模式注册直接成功
    final r = await http.post(
      _uri('/auth/register'),
      headers: _headers(),
      body: jsonEncode({
        'email': email,
        'verification_code': verificationCode,
        'username': username,
        'password': password,
        'account_role': accountRole,
      }),
    );
    if (r.statusCode != 201) _fail(r);
  }

  Future<int> sendBindEmailCode(String email) async {
    if (kOfflineMode) return 60;
    final r = await http.post(
      _uri('/auth/email/bind/send-code'),
      headers: _headers(auth: true),
      body: jsonEncode({'email': email}),
    );
    if (r.statusCode != 202) _fail(r);
    final data = _decode(r) as Map<String, dynamic>;
    return data['retry_after_seconds'] as int? ?? 60;
  }

  Future<void> bindEmail(String email, String verificationCode) async {
    if (kOfflineMode) {
      this.email = email;
      return;
    }
    final r = await http.post(
      _uri('/auth/email/bind'),
      headers: _headers(auth: true),
      body: jsonEncode({'email': email, 'verification_code': verificationCode}),
    );
    if (r.statusCode != 200) _fail(r);
    this.email = (_decode(r) as Map<String, dynamic>)['email'] as String;
  }

  Future<void> login(String username, String password) async {
    if (kOfflineMode) {
      _offlineLogin(username);
      return;
    }
    final r = await http.post(
      _uri('/auth/login'),
      headers: _headers(),
      body: jsonEncode({'username': username, 'password': password}),
    );
    if (r.statusCode != 200) _fail(r);
    final data = _decode(r) as Map<String, dynamic>;
    sessionId = data['session_id'] as String;
    userId = data['user_id'] as String;
    this.username = data['username'] as String;
    email = data['email'] as String?;
    accountRole = data['account_role'] as String? ?? 'student';
    sessionExpiresAt = DateTime.tryParse(data['expires_at'] as String? ?? '');
  }

  Future<void> logout() async {
    if (kOfflineMode) {
      sessionId = null;
      userId = null;
      username = null;
      email = null;
      sessionExpiresAt = null;
      return;
    }
    if (sessionId == null) return;
    try {
      await http.post(_uri('/auth/logout'), headers: _headers(auth: true));
    } catch (_) {
      // 登出失败也无所谓 本地清理即可
    } finally {
      sessionId = null;
      userId = null;
      username = null;
      email = null;
      sessionExpiresAt = null;
    }
  }

  Future<void> changePassword(String oldPassword, String newPassword) async {
    if (kOfflineMode) return;
    final r = await http.post(
      _uri('/auth/change-password'),
      headers: _headers(auth: true),
      body: jsonEncode({
        'old_password': oldPassword,
        'new_password': newPassword,
      }),
    );
    if (r.statusCode != 204) _fail(r);
  }

  // ---------- 输出偏好 / 学情档案 ----------
  Future<UserPreferences> getPreferences() async {
    if (kOfflineMode) return const UserPreferences();
    final r = await http.get(
      _uri('/me/preferences'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    return UserPreferences.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<UserPreferences> updatePreferences({
    required String preferredStyle,
    required String preferredTone,
    required String customInstruction,
  }) async {
    if (kOfflineMode) {
      return UserPreferences(
        preferredStyle: preferredStyle,
        preferredTone: preferredTone,
        customInstruction: customInstruction,
      );
    }
    final r = await http.patch(
      _uri('/me/preferences'),
      headers: _headers(auth: true),
      body: jsonEncode({
        'preferred_style': preferredStyle,
        'preferred_tone': preferredTone,
        'custom_instruction': customInstruction,
      }),
    );
    if (r.statusCode != 200) _fail(r);
    return UserPreferences.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<UserProfile> getProfile() async {
    if (kOfflineMode) return const UserProfile();
    final r = await http.get(
      _uri('/me/profile'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    return UserProfile.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<UserProfile> updateProfile({
    required String major,
    required String grade,
    required int currentWeek,
    required int totalWeeks,
    required bool profileEnabled,
  }) async {
    if (kOfflineMode) {
      return UserProfile(
        major: major,
        grade: grade,
        currentWeek: currentWeek,
        totalWeeks: totalWeeks,
        profileEnabled: profileEnabled,
      );
    }
    final r = await http.patch(
      _uri('/me/profile'),
      headers: _headers(auth: true),
      body: jsonEncode({
        'major': major,
        'grade': grade,
        'current_week': currentWeek,
        'total_weeks': totalWeeks,
        'profile_enabled': profileEnabled,
      }),
    );
    if (r.statusCode != 200) _fail(r);
    return UserProfile.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<MasteryReport> getMasteryReport({String course = ''}) async {
    final query = course.trim().isEmpty
        ? ''
        : '?course=${Uri.encodeQueryComponent(course.trim())}';
    final r = await http.get(
      _uri('/me/learning/mastery$query'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    return MasteryReport.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<List<LearningCourseSummary>> getLearningCourses() async {
    final r = await http.get(
      _uri('/me/learning/courses'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    final data = _decode(r) as Map<String, dynamic>;
    return (data['courses'] as List? ?? const [])
        .whereType<Map>()
        .map(
          (item) =>
              LearningCourseSummary.fromJson(Map<String, dynamic>.from(item)),
        )
        .where((item) => item.name.isNotEmpty)
        .toList();
  }

  Future<List<LearningCourseCatalogItem>> getLearningCourseCatalog({
    String query = '',
  }) async {
    final suffix = query.trim().isEmpty
        ? ''
        : '?query=${Uri.encodeQueryComponent(query.trim())}';
    final r = await http.get(
      _uri('/me/learning/course-catalog$suffix'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    final data = _decode(r) as Map<String, dynamic>;
    return (data['courses'] as List? ?? const [])
        .whereType<Map>()
        .map(
          (item) => LearningCourseCatalogItem.fromJson(
            Map<String, dynamic>.from(item),
          ),
        )
        .where((item) => item.name.isNotEmpty)
        .toList();
  }

  Future<void> addLearningCourses(
    Iterable<String> names, {
    required String source,
  }) async {
    final courses = names
        .map((name) => name.trim())
        .where((name) => name.isNotEmpty)
        .map((name) => {'name': name, 'source': source})
        .toList();
    if (courses.isEmpty) return;
    final r = await http.post(
      _uri('/me/learning/courses'),
      headers: _headers(auth: true),
      body: jsonEncode({'courses': courses}),
    );
    if (r.statusCode != 201) _fail(r);
  }

  Future<void> removeLearningCourse(String name) async {
    final r = await http.delete(
      _uri('/me/learning/courses/${Uri.encodeComponent(name.trim())}'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 204) _fail(r);
  }

  Future<void> bindLearningCourse({
    required String name,
    required String canonicalCourse,
  }) async {
    final r = await http.patch(
      _uri('/me/learning/courses/${Uri.encodeComponent(name.trim())}'),
      headers: _headers(auth: true),
      body: jsonEncode({'canonical_course': canonicalCourse.trim()}),
    );
    if (r.statusCode != 200) _fail(r);
  }

  Future<ScheduleSnapshot> getSchedule() async {
    final r = await http.get(
      _uri('/me/schedule'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    return ScheduleSnapshot.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<ScheduleCourse> saveScheduleCourse(ScheduleCourse course) async {
    final r = await http.put(
      _uri('/me/schedule/courses'),
      headers: _headers(auth: true),
      body: jsonEncode(course.toJson()),
    );
    if (r.statusCode != 200) _fail(r);
    return ScheduleCourse.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<void> deleteScheduleCourse(String courseId) async {
    final r = await http.delete(
      _uri('/me/schedule/courses/${Uri.encodeComponent(courseId)}'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 204) _fail(r);
  }

  Future<ScheduleSettings> saveScheduleSettings(
    ScheduleSettings settings,
  ) async {
    final r = await http.put(
      _uri('/me/schedule/settings'),
      headers: _headers(auth: true),
      body: jsonEncode(settings.toJson()),
    );
    if (r.statusCode != 200) _fail(r);
    return ScheduleSettings.fromJson(_decode(r) as Map<String, dynamic>);
  }

  /// 按魔数优先、扩展名兜底推断 MIME。Android 相册/第三方文件提供器给出的
  /// 文件名可能没有扩展名，后端判定完全依赖 content_type 或扩展名，两者
  /// 都缺时合法图片也会被 422 拒绝。
  static String _mimeFor(String filename, Uint8List bytes) {
    if (bytes.length >= 12) {
      if (bytes[0] == 0x25 && bytes[1] == 0x50 && bytes[2] == 0x44) {
        return 'application/pdf'; // %PDF
      }
      if (bytes[0] == 0x89 && bytes[1] == 0x50) return 'image/png';
      if (bytes[0] == 0xFF && bytes[1] == 0xD8) return 'image/jpeg';
      if (bytes[0] == 0x42 && bytes[1] == 0x4D) return 'image/bmp';
      if (bytes[0] == 0x52 &&
          bytes[1] == 0x49 &&
          bytes[8] == 0x57 &&
          bytes[9] == 0x45) {
        return 'image/webp'; // RIFF....WEBP
      }
      if (bytes[4] == 0x66 &&
          bytes[5] == 0x74 &&
          bytes[6] == 0x79 &&
          bytes[7] == 0x70) {
        return 'image/heic'; // ....ftyp
      }
    }
    final ext = filename.contains('.')
        ? filename.toLowerCase().split('.').last
        : '';
    return switch (ext) {
      'pdf' => 'application/pdf',
      'png' => 'image/png',
      'jpg' || 'jpeg' => 'image/jpeg',
      'webp' => 'image/webp',
      'bmp' => 'image/bmp',
      'heic' || 'heif' => 'image/heic',
      'gif' => 'image/gif',
      'tif' || 'tiff' => 'image/tiff',
      'docx' =>
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'pptx' =>
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      'xlsx' =>
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'html' || 'htm' => 'text/html',
      _ => 'application/octet-stream',
    };
  }

  Future<ScheduleImportResult> importScheduleFile({
    required String filename,
    required Uint8List bytes,
    bool toNewTable = false,
    String? newTableName,
  }) async {
    final request = http.MultipartRequest('POST', _uri('/me/schedule/import'));
    if (sessionId != null) {
      request.headers['Authorization'] = 'Bearer $sessionId';
    }
    request.fields['target'] = toNewTable ? 'new' : 'current';
    if (toNewTable && newTableName != null && newTableName.trim().isNotEmpty) {
      request.fields['table_name'] = newTableName.trim();
    }
    request.files.add(
      http.MultipartFile.fromBytes(
        'file',
        bytes,
        filename: filename,
        contentType: MediaType.parse(_mimeFor(filename, bytes)),
      ),
    );
    // 后端 LLM 识别多页 PDF 可能要几十秒；但手机弱网下不能无限挂起，
    // 否则 _importing 永远为 true、导入按钮永久禁用
    try {
      final streamed = await request.send().timeout(
        const Duration(seconds: 180),
      );
      final r = await http.Response.fromStream(
        streamed,
      ).timeout(const Duration(seconds: 60));
      if (r.statusCode != 200) _fail(r);
      final data = _decode(r) as Map<String, dynamic>;
      return ScheduleImportResult(
        courses: (data['courses'] as List? ?? const [])
            .whereType<Map>()
            .map(
              (item) =>
                  ScheduleCourse.fromJson(Map<String, dynamic>.from(item)),
            )
            .toList(),
        skippedCount: (data['skipped_count'] as num?)?.toInt() ?? 0,
        documentPipeline:
            (data['document'] as Map?)?['pipeline']?.toString() ?? 'legacy',
        documentId: (data['document'] as Map?)?['document_id']?.toString(),
      );
    } on TimeoutException {
      throw ApiException(0, '课表识别超时，请稍后重试');
    } on http.ClientException {
      throw ApiException(0, '网络异常，请检查网络后重试');
    }
  }

  Future<ScheduleTable> createScheduleTable(String name) async {
    final r = await http.post(
      _uri('/me/schedule/tables'),
      headers: _headers(auth: true),
      body: jsonEncode({'name': name}),
    );
    if (r.statusCode != 201) _fail(r);
    return ScheduleTable.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<ScheduleTable> renameScheduleTable(String tableId, String name) async {
    final r = await http.patch(
      _uri('/me/schedule/tables/$tableId'),
      headers: _headers(auth: true),
      body: jsonEncode({'name': name}),
    );
    if (r.statusCode != 200) _fail(r);
    return ScheduleTable.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<ScheduleSnapshot> activateScheduleTable(String tableId) async {
    final r = await http.post(
      _uri('/me/schedule/tables/$tableId/activate'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    return ScheduleSnapshot.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<void> deleteScheduleTable(String tableId) async {
    final r = await http.delete(
      _uri('/me/schedule/tables/$tableId'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 204) _fail(r);
  }

  Future<KnowledgeMapData> getKnowledgeMap(String course) async {
    final query = Uri.encodeQueryComponent(course.trim());
    final r = await http.get(
      _uri('/me/learning/knowledge-map?course=$query'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    return KnowledgeMapData.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<KnowledgePointDetail> getKnowledgePointDetail(String kpId) async {
    final r = await http.get(
      _uri('/me/learning/knowledge-points/${Uri.encodeComponent(kpId)}'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    return KnowledgePointDetail(raw: _decode(r) as Map<String, dynamic>);
  }

  Future<List<CoreMemoryItem>> listCoreMemories() async {
    final r = await http.get(
      _uri('/me/memories'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    return (_decode(r) as List)
        .whereType<Map>()
        .map((item) => CoreMemoryItem.fromJson(Map<String, dynamic>.from(item)))
        .toList();
  }

  Future<void> saveCoreMemory({
    required String key,
    required String content,
    required String category,
  }) async {
    final r = await http.put(
      _uri('/me/memories'),
      headers: _headers(auth: true),
      body: jsonEncode({
        'memory_key': key,
        'content': content,
        'category': category,
      }),
    );
    if (r.statusCode != 201) _fail(r);
  }

  Future<void> deleteCoreMemory(String key) async {
    final r = await http.delete(
      _uri('/me/memories/${Uri.encodeComponent(key)}'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 204) _fail(r);
  }

  // ---------- 对话分组 ----------
  Future<List<ChatGroup>> listGroups() async {
    if (kOfflineMode) return List.of(_offGroups);
    final r = await http.get(_uri('/groups'), headers: _headers(auth: true));
    if (r.statusCode != 200) _fail(r);
    final list = _decode(r) as List;
    return list
        .map((e) => ChatGroup.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<ChatGroup> createGroup({
    required String name,
    String description = '',
    String customInstruction = '',
    String? style,
    String? tone,
  }) async {
    if (kOfflineMode) {
      final now = DateTime.now();
      final group = ChatGroup(
        id: _offGroupId(),
        userId: userId ?? 'offline-user',
        name: name,
        description: description,
        customInstruction: customInstruction,
        style: style,
        tone: tone,
        conversationCount: 0,
        createdAt: now,
        updatedAt: now,
      );
      _offGroups.insert(0, group);
      return group;
    }
    final r = await http.post(
      _uri('/groups'),
      headers: _headers(auth: true),
      body: jsonEncode({
        'name': name,
        'description': description,
        'custom_instruction': customInstruction,
        'style': ?style,
        'tone': ?tone,
      }),
    );
    if (r.statusCode != 201) _fail(r);
    return ChatGroup.fromJson(_decode(r) as Map<String, dynamic>);
  }

  /// 传 null 给 [style] / [tone] 表示恢复为用户级继承；不传则不修改。
  Future<ChatGroup> updateGroup(
    String groupId, {
    String? name,
    String? description,
    String? customInstruction,
    Object? style = groupFieldUnset,
    Object? tone = groupFieldUnset,
  }) async {
    if (kOfflineMode) {
      final index = _offGroups.indexWhere((group) => group.id == groupId);
      if (index < 0) throw ApiException(404, '分组不存在');
      final current = _offGroups[index];
      final updated = ChatGroup(
        id: current.id,
        userId: current.userId,
        name: name ?? current.name,
        description: description ?? current.description,
        customInstruction: customInstruction ?? current.customInstruction,
        style: identical(style, groupFieldUnset)
            ? current.style
            : style as String?,
        tone: identical(tone, groupFieldUnset) ? current.tone : tone as String?,
        conversationCount: current.conversationCount,
        createdAt: current.createdAt,
        updatedAt: DateTime.now(),
      );
      _offGroups[index] = updated;
      return updated;
    }
    final body = <String, dynamic>{
      'name': ?name,
      'description': ?description,
      'custom_instruction': ?customInstruction,
      if (!identical(style, groupFieldUnset)) 'style': style as String?,
      if (!identical(tone, groupFieldUnset)) 'tone': tone as String?,
    };
    final r = await http.patch(
      _uri('/groups/${Uri.encodeComponent(groupId)}'),
      headers: _headers(auth: true),
      body: jsonEncode(body),
    );
    if (r.statusCode != 200) _fail(r);
    return ChatGroup.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<void> deleteGroup(String groupId) async {
    if (kOfflineMode) {
      _offGroups.removeWhere((group) => group.id == groupId);
      return;
    }
    final r = await http.delete(
      _uri('/groups/${Uri.encodeComponent(groupId)}'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 204) _fail(r);
  }

  // ---------- 对话 ----------
  Future<WorkspaceManifest> getWorkspaceManifest() async {
    if (kOfflineMode) {
      final types = accountRole == 'teacher'
          ? [WorkspaceType.teaching, WorkspaceType.research]
          : [WorkspaceType.learning, WorkspaceType.research];
      return WorkspaceManifest(
        accountRole: accountRole,
        defaultWorkspace: types.first,
        workspaces: types
            .map(
              (type) => WorkspaceDescriptor(
                type: type,
                name: type.label,
                description: '',
                capabilities: const ['chat'],
              ),
            )
            .toList(),
      );
    }
    final response = await http.get(
      _uri('/workspaces'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return WorkspaceManifest.fromJson(
      _decode(response) as Map<String, dynamic>,
    );
  }

  Future<List<ChatConversation>> listConversations() async {
    if (kOfflineMode) {
      return _offConvs
          .where((item) => item.workspaceType == WorkspaceType.learning)
          .toList();
    }
    final r = await http.get(
      _uri('/conversations?workspace_type=learning'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    final list = _decode(r) as List;
    return list
        .map((e) => ChatConversation.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<ChatConversation>> listWorkspaceConversations(
    WorkspaceType workspace,
  ) async {
    if (kOfflineMode) {
      return _offConvs
          .where((item) => item.workspaceType == workspace)
          .toList();
    }
    final response = await http.get(
      _uri('/conversations?workspace_type=${workspace.wireName}'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    final list = _decode(response) as List;
    return list
        .map((item) => ChatConversation.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<ChatConversation> createConversation({String? groupId}) async {
    if (kOfflineMode) return _offlineNewConversation(groupId: groupId);
    final r = await http.post(
      _uri('/conversations'),
      headers: _headers(auth: true),
      body: jsonEncode({'group_id': ?groupId}),
    );
    if (r.statusCode != 201) _fail(r);
    return ChatConversation.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<ChatConversation> createWorkspaceConversation(
    WorkspaceType workspace, {
    String? researchProjectId,
    String? groupId,
  }) async {
    if (workspace == WorkspaceType.learning && researchProjectId == null) {
      return createConversation(groupId: groupId);
    }
    if (kOfflineMode) {
      return _offlineNewConversation(
        workspaceType: workspace,
        researchProjectId: researchProjectId,
        groupId: groupId,
      );
    }
    final body = <String, String>{'workspace_type': workspace.wireName};
    if (researchProjectId case final projectId?) {
      body['research_project_id'] = projectId;
    }
    if (groupId case final selectedGroupId?) {
      body['group_id'] = selectedGroupId;
    }
    final response = await http.post(
      _uri('/conversations'),
      headers: _headers(auth: true),
      body: jsonEncode(body),
    );
    if (response.statusCode != 201) _fail(response);
    return ChatConversation.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<List<ResearchProject>> listResearchProjects() async {
    if (kOfflineMode) return List.of(_offResearchProjects);
    final response = await http.get(
      _uri('/research/projects'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return (_decode(response) as List)
        .map((item) => ResearchProject.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<ResearchProject> createResearchProject(
    String name,
    String description,
  ) async {
    if (kOfflineMode) {
      final project = ResearchProject(
        id: _offId(),
        name: name,
        description: description,
        status: 'active',
        updatedAt: DateTime.now(),
      );
      _offResearchProjects.insert(0, project);
      return project;
    }
    final response = await http.post(
      _uri('/research/projects'),
      headers: _headers(auth: true),
      body: jsonEncode({'name': name, 'description': description}),
    );
    if (response.statusCode != 201) _fail(response);
    return ResearchProject.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<void> archiveResearchProject(String id) async {
    if (kOfflineMode) {
      _offResearchProjects.removeWhere((item) => item.id == id);
      return;
    }
    final response = await http.patch(
      _uri('/research/projects/$id'),
      headers: _headers(auth: true),
      body: jsonEncode({'status': 'archived'}),
    );
    if (response.statusCode != 200) _fail(response);
  }

  Future<ResearchProject> updateResearchProject(
    String id, {
    required String name,
    required String description,
  }) async {
    if (kOfflineMode) {
      final index = _offResearchProjects.indexWhere((item) => item.id == id);
      if (index < 0) throw ApiException(404, '科研项目不存在');
      final updated = _offResearchProjects[index].copyWith(
        name: name,
        description: description,
        updatedAt: DateTime.now(),
      );
      _offResearchProjects[index] = updated;
      return updated;
    }
    final response = await http.patch(
      _uri('/research/projects/$id'),
      headers: _headers(auth: true),
      body: jsonEncode({'name': name, 'description': description}),
    );
    if (response.statusCode != 200) _fail(response);
    return ResearchProject.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<List<FrontierTrackingJob>> listFrontierJobs(String projectId) async {
    final response = await http.get(
      _uri('/research/projects/$projectId/frontier-jobs'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return (_decode(response) as List)
        .whereType<Map>()
        .map(
          (item) =>
              FrontierTrackingJob.fromJson(Map<String, dynamic>.from(item)),
        )
        .toList();
  }

  Future<FrontierTrackingJob> createFrontierJob(
    String projectId,
    String query, {
    int timeWindowYears = 5,
    int maxResults = 20,
  }) async {
    final response = await http.post(
      _uri('/research/projects/$projectId/frontier-jobs'),
      headers: _headers(auth: true),
      body: jsonEncode({
        'query': query,
        'time_window_years': timeWindowYears,
        'max_results': maxResults,
      }),
    );
    if (response.statusCode != 202) _fail(response);
    return FrontierTrackingJob.fromJson(
      _decode(response) as Map<String, dynamic>,
    );
  }

  Future<FrontierTrackingJob> getFrontierJob(String jobId) async {
    final response = await http.get(
      _uri('/research/frontier-jobs/$jobId'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return FrontierTrackingJob.fromJson(
      _decode(response) as Map<String, dynamic>,
    );
  }

  Future<List<ResearchDocument>> listResearchDocuments(String projectId) async {
    final response = await http.get(
      _uri('/research/projects/$projectId/documents'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return (_decode(response) as List)
        .whereType<Map>()
        .map(
          (item) => ResearchDocument.fromJson(Map<String, dynamic>.from(item)),
        )
        .toList();
  }

  Future<ResearchDocument> createResearchDocument({
    required String projectId,
    required String title,
    required String type,
    String content = '',
  }) async {
    final response = await http.post(
      _uri('/research/projects/$projectId/documents'),
      headers: _headers(auth: true),
      body: jsonEncode({
        'title': title,
        'document_type': type,
        'content': content,
      }),
    );
    if (response.statusCode != 201) _fail(response);
    return ResearchDocument.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<ResearchDocument> getResearchDocument(String documentId) async {
    final response = await http.get(
      _uri('/research/documents/$documentId'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return ResearchDocument.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<ResearchDocument> updateResearchDocument({
    required String documentId,
    required String content,
  }) async {
    final response = await http.patch(
      _uri('/research/documents/$documentId'),
      headers: _headers(auth: true),
      body: jsonEncode({'content': content}),
    );
    if (response.statusCode != 200) _fail(response);
    return ResearchDocument.fromJson(
      _decode(response) as Map<String, dynamic>,
    );
  }

  Future<AttachmentContent> fetchConversationAttachment(
    String conversationId,
    DocumentAttachment attachment,
  ) async {
    final response = await http.get(
      _uri('/conversations/$conversationId/attachments/${attachment.id}'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return AttachmentContent(
      bytes: response.bodyBytes,
      mediaType:
          response.headers['content-type'] ?? attachment.mediaType,
      filename: attachment.filename,
    );
  }

  Future<ResearchWritingJob> createWritingJob({
    required String documentId,
    required String operation,
    String instruction = '',
    String sourceText = '',
  }) async {
    final response = await http.post(
      _uri('/research/documents/$documentId/writing-jobs'),
      headers: _headers(auth: true),
      body: jsonEncode({
        'operation': operation,
        'instruction': instruction,
        'source_text': sourceText,
      }),
    );
    if (response.statusCode != 202) _fail(response);
    return ResearchWritingJob.fromJson(
      _decode(response) as Map<String, dynamic>,
    );
  }

  Future<ResearchWritingJob> getWritingJob(String jobId) async {
    final response = await http.get(
      _uri('/research/writing-jobs/$jobId'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return ResearchWritingJob.fromJson(
      _decode(response) as Map<String, dynamic>,
    );
  }

  Future<List<ResearchDataset>> listResearchDatasets(String projectId) async {
    final response = await http.get(
      _uri('/research/projects/$projectId/datasets'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return (_decode(response) as List)
        .whereType<Map>()
        .map(
          (item) => ResearchDataset.fromJson(Map<String, dynamic>.from(item)),
        )
        .toList();
  }

  Future<ResearchDataset> uploadResearchDataset({
    required String projectId,
    required String name,
    required String filename,
    required Uint8List bytes,
  }) async {
    final request = http.MultipartRequest(
      'POST',
      _uri('/research/projects/$projectId/datasets'),
    );
    if (sessionId != null) {
      request.headers['Authorization'] = 'Bearer $sessionId';
    }
    request.fields['name'] = name;
    request.files.add(
      http.MultipartFile.fromBytes('file', bytes, filename: filename),
    );
    final streamed = await request.send().timeout(const Duration(minutes: 2));
    final response = await http.Response.fromStream(streamed);
    if (response.statusCode != 201) _fail(response);
    return ResearchDataset.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<ResearchAnalysisJob> createAnalysisJob({
    required String datasetId,
    required String type,
    Map<String, String> parameters = const {},
  }) async {
    final response = await http.post(
      _uri('/research/datasets/$datasetId/analysis-jobs'),
      headers: _headers(auth: true),
      body: jsonEncode({'analysis_type': type, 'parameters': parameters}),
    );
    if (response.statusCode != 202) _fail(response);
    return ResearchAnalysisJob.fromJson(
      _decode(response) as Map<String, dynamic>,
    );
  }

  Future<ResearchAnalysisJob> getAnalysisJob(String jobId) async {
    final response = await http.get(
      _uri('/research/analysis-jobs/$jobId'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return ResearchAnalysisJob.fromJson(
      _decode(response) as Map<String, dynamic>,
    );
  }

  Future<void> renameConversation(String id, String title) async {
    if (kOfflineMode) {
      for (final c in _offConvs) {
        if (c.id == id) c.title = title;
      }
      return;
    }
    final r = await http.patch(
      _uri('/conversations/$id'),
      headers: _headers(auth: true),
      body: jsonEncode({'title': title}),
    );
    if (r.statusCode != 204) _fail(r);
  }

  Future<void> moveConversation(String id, String? groupId) async {
    if (kOfflineMode) {
      final index = _offConvs.indexWhere((c) => c.id == id);
      if (index >= 0) _offConvs[index].groupId = groupId;
      return;
    }
    final r = await http.patch(
      _uri('/conversations/${Uri.encodeComponent(id)}'),
      headers: _headers(auth: true),
      body: jsonEncode({'group_id': groupId}),
    );
    if (r.statusCode != 204) _fail(r);
  }

  Future<void> deleteConversation(String id) async {
    if (kOfflineMode) {
      _offConvs.removeWhere((c) => c.id == id);
      _offMsgs.remove(id);
      return;
    }
    final r = await http.delete(
      _uri('/conversations/$id'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 204) _fail(r);
  }

  Future<List<ChatMessage>> getMessages(String id) async {
    if (kOfflineMode) return List.of(_offMsgs[id] ?? const []);
    final r = await http.get(
      _uri('/conversations/$id/messages'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    final list = _decode(r) as List;
    return list
        .map((e) => ChatMessage.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<ChatMessage>> sendMessage(String id, String content) async {
    if (kOfflineMode) return _offlineSend(id, content);
    final r = await http.post(
      _uri('/conversations/$id/messages'),
      headers: _headers(auth: true),
      body: jsonEncode({'content': content}),
    );
    if (r.statusCode != 200) _fail(r);
    final list = _decode(r) as List;
    return list
        .map((e) => ChatMessage.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<ChatMessage>> sendMessageWithAttachments(
    String id,
    String content,
    List<String> attachmentIds,
  ) async {
    final r = await http.post(
      _uri('/conversations/$id/messages'),
      headers: _headers(auth: true),
      body: jsonEncode({'content': content, 'attachment_ids': attachmentIds}),
    );
    if (r.statusCode != 200) _fail(r);
    final list = _decode(r) as List;
    return list
        .map((e) => ChatMessage.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<DocumentAttachment> uploadConversationAttachment({
    required String conversationId,
    required String filename,
    required Stream<List<int>> stream,
    required int length,
  }) async {
    final request = http.MultipartRequest(
      'POST',
      _uri('/conversations/$conversationId/attachments'),
    );
    if (sessionId != null) {
      request.headers['Authorization'] = 'Bearer $sessionId';
    }
    request.files.add(
      http.MultipartFile(
        'file',
        stream,
        length,
        filename: filename,
        contentType: MediaType.parse(_mimeFor(filename, Uint8List(0))),
      ),
    );
    try {
      final streamed = await request.send().timeout(
        const Duration(minutes: 10),
      );
      final response = await http.Response.fromStream(
        streamed,
      ).timeout(const Duration(minutes: 2));
      if (response.statusCode != 201) _fail(response);
      return DocumentAttachment.fromJson(
        _decode(response) as Map<String, dynamic>,
      );
    } on TimeoutException {
      throw ApiException(0, 'DocIR 解析超时，请稍后重试');
    } on http.ClientException {
      throw ApiException(0, '网络异常，请检查网络后重试');
    }
  }

  Future<void> deleteConversationAttachment(
    String conversationId,
    String attachmentId,
  ) async {
    final r = await http.delete(
      _uri('/conversations/$conversationId/attachments/$attachmentId'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 204 && r.statusCode != 404) _fail(r);
  }

  Stream<ChatStreamEvent> streamMessage(String id, String content) async* {
    if (kOfflineMode) {
      final messages = await _offlineSend(id, content);
      yield const ChatStreamEvent('start', {});
      for (final message in messages) {
        if (message.isTool) {
          yield ChatStreamEvent('tool', {
            'name': message.name,
            'content': message.text,
          });
        } else if (!message.isUser) {
          if (message.reasoning.isNotEmpty) {
            yield ChatStreamEvent('reasoning', {'delta': message.reasoning});
          }
          if (message.text.isNotEmpty) {
            yield ChatStreamEvent('content', {'delta': message.text});
          }
        }
      }
      yield const ChatStreamEvent('done', {});
      return;
    }

    final request =
        http.Request('POST', _uri('/conversations/$id/messages/stream'))
          ..headers.addAll(_headers(auth: true))
          ..body = jsonEncode({'content': content});

    final response = await request.send();
    if (response.statusCode != 200) {
      final bytes = await response.stream.toBytes();
      _fail(http.Response.bytes(bytes, response.statusCode));
    }

    yield* _decodeSse(response.stream);
  }

  Stream<ChatStreamEvent> streamMessageWithAttachments(
    String id,
    String content,
    List<String> attachmentIds,
  ) async* {
    final request =
        http.Request('POST', _uri('/conversations/$id/messages/stream'))
          ..headers.addAll(_headers(auth: true))
          ..body = jsonEncode({
            'content': content,
            'attachment_ids': attachmentIds,
          });

    final response = await request.send();
    if (response.statusCode != 200) {
      final bytes = await response.stream.toBytes();
      _fail(http.Response.bytes(bytes, response.statusCode));
    }
    yield* _decodeSse(response.stream);
  }

  Stream<ChatStreamEvent> streamRevisedMessage(
    String id,
    String content,
    int messageId,
    List<String> attachmentIds,
  ) async* {
    final request =
        http.Request('POST', _uri('/conversations/$id/messages/stream'))
          ..headers.addAll(_headers(auth: true))
          ..body = jsonEncode({
            'content': content,
            'attachment_ids': attachmentIds,
            'replace_message_id': messageId,
          });
    final response = await request.send();
    if (response.statusCode != 200) {
      final bytes = await response.stream.toBytes();
      _fail(http.Response.bytes(bytes, response.statusCode));
    }
    yield* _decodeSse(response.stream);
  }

  Stream<ChatStreamEvent> _decodeSse(Stream<List<int>> stream) async* {
    String eventName = 'message';
    final dataLines = <String>[];
    await for (final line
        in stream.transform(utf8.decoder).transform(const LineSplitter())) {
      if (line.isEmpty) {
        if (dataLines.isNotEmpty) {
          final decoded = jsonDecode(dataLines.join('\n'));
          if (decoded is Map<String, dynamic>) {
            yield ChatStreamEvent(eventName, decoded);
          }
        }
        eventName = 'message';
        dataLines.clear();
        continue;
      }
      if (line.startsWith(':')) continue;
      if (line.startsWith('event:')) {
        eventName = line.substring('event:'.length).trim();
      } else if (line.startsWith('data:')) {
        dataLines.add(line.substring('data:'.length).trimLeft());
      }
    }
    if (dataLines.isNotEmpty) {
      final decoded = jsonDecode(dataLines.join('\n'));
      if (decoded is Map<String, dynamic>) {
        yield ChatStreamEvent(eventName, decoded);
      }
    }
  }

  // ---------- 教师端与学生端 ----------
  Future<Map<String, dynamic>> getTeachingOverview() async {
    final response = await http.get(
      _uri('/teaching/overview'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return Map<String, dynamic>.from(_decode(response) as Map);
  }

  Future<TeachingClass> createTeachingClass({
    required String name,
    required String course,
    String term = '',
    String description = '',
  }) async {
    final response = await http.post(
      _uri('/teaching/classes'),
      headers: _headers(auth: true),
      body: jsonEncode({
        'name': name,
        'canonical_course': course,
        'term': term,
        'description': description,
      }),
    );
    if (response.statusCode != 201) _fail(response);
    return TeachingClass.fromJson(
      Map<String, dynamic>.from(_decode(response) as Map),
    );
  }

  Future<Map<String, dynamic>> getTeachingClass(String classId) async {
    final response = await http.get(
      _uri('/teaching/classes/$classId'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return Map<String, dynamic>.from(_decode(response) as Map);
  }

  Future<void> inviteStudent(String classId, String username) async {
    final response = await http.post(
      _uri('/teaching/classes/$classId/invitations'),
      headers: _headers(auth: true),
      body: jsonEncode({'username': username}),
    );
    if (response.statusCode != 201) _fail(response);
  }

  Future<TeachingAssignment> createTeachingAssignment({
    required String classId,
    required String title,
    required String instructions,
    required List<Map<String, dynamic>> questions,
    DateTime? dueAt,
  }) async {
    final response = await http.post(
      _uri('/teaching/classes/$classId/assignments'),
      headers: _headers(auth: true),
      body: jsonEncode({
        'title': title,
        'instructions': instructions,
        'due_at': dueAt?.toUtc().toIso8601String(),
        'questions': questions,
      }),
    );
    if (response.statusCode != 201) _fail(response);
    return TeachingAssignment.fromJson(
      Map<String, dynamic>.from(_decode(response) as Map),
    );
  }

  Future<TeachingAssignment> publishTeachingAssignment(String id) async {
    final response = await http.post(
      _uri('/teaching/assignments/$id/publish'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return TeachingAssignment.fromJson(
      Map<String, dynamic>.from(_decode(response) as Map),
    );
  }

  Future<List<TeachingSubmission>> listTeachingSubmissions(String id) async {
    final response = await http.get(
      _uri('/teaching/assignments/$id/submissions'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return (_decode(response) as List)
        .whereType<Map>()
        .map(
          (item) =>
              TeachingSubmission.fromJson(Map<String, dynamic>.from(item)),
        )
        .toList();
  }

  Future<TeachingSubmission> getTeachingSubmission(String id) async {
    final response = await http.get(
      _uri('/teaching/submissions/$id'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return TeachingSubmission.fromJson(
      Map<String, dynamic>.from(_decode(response) as Map),
    );
  }

  Future<TeachingSubmission> analyzeTeachingSubmission(String id) async {
    final response = await http.post(
      _uri('/teaching/submissions/$id/analyze'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return TeachingSubmission.fromJson(
      Map<String, dynamic>.from(_decode(response) as Map),
    );
  }

  Future<Map<String, dynamic>> analyzeTeachingAssignment(String id) async {
    final response = await http.post(
      _uri('/teaching/assignments/$id/analyze'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return Map<String, dynamic>.from(_decode(response) as Map);
  }

  Future<TeachingSubmission> reviewTeachingSubmission(
    String id,
    List<Map<String, dynamic>> reviews,
  ) async {
    final response = await http.post(
      _uri('/teaching/submissions/$id/review'),
      headers: _headers(auth: true),
      body: jsonEncode({'reviews': reviews}),
    );
    if (response.statusCode != 200) _fail(response);
    return TeachingSubmission.fromJson(
      Map<String, dynamic>.from(_decode(response) as Map),
    );
  }

  Future<TeachingSubmission> publishTeachingFeedback(String id) async {
    final response = await http.post(
      _uri('/teaching/submissions/$id/publish-feedback'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return TeachingSubmission.fromJson(
      Map<String, dynamic>.from(_decode(response) as Map),
    );
  }

  Future<Map<String, dynamic>> getClassDashboard(String classId) async {
    final response = await http.get(
      _uri('/teaching/classes/$classId/dashboard'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return Map<String, dynamic>.from(_decode(response) as Map);
  }

  Future<List<TeachingClass>> listStudentClasses() async {
    final response = await http.get(
      _uri('/student/classes'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return (_decode(response) as List)
        .whereType<Map>()
        .map((item) => TeachingClass.fromJson(Map<String, dynamic>.from(item)))
        .toList();
  }

  Future<void> respondClassInvitation(String membershipId, bool accept) async {
    final response = await http.post(
      _uri('/student/invitations/$membershipId/respond'),
      headers: _headers(auth: true),
      body: jsonEncode({'accept': accept}),
    );
    if (response.statusCode != 200) _fail(response);
  }

  Future<List<TeachingAssignment>> listStudentAssignments() async {
    final response = await http.get(
      _uri('/student/assignments'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return (_decode(response) as List)
        .whereType<Map>()
        .map(
          (item) =>
              TeachingAssignment.fromJson(Map<String, dynamic>.from(item)),
        )
        .toList();
  }

  Future<TeachingAssignment> getStudentAssignment(String id) async {
    final response = await http.get(
      _uri('/student/assignments/$id'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return TeachingAssignment.fromJson(
      Map<String, dynamic>.from(_decode(response) as Map),
    );
  }

  Future<TeachingSubmission> submitAssignment(
    String id,
    Map<String, String> answers,
  ) async {
    final response = await http.post(
      _uri('/student/assignments/$id/submissions'),
      headers: _headers(auth: true),
      body: jsonEncode({
        'answers': answers.entries
            .map((item) => {'question_id': item.key, 'answer_text': item.value})
            .toList(),
      }),
    );
    if (response.statusCode != 201) _fail(response);
    return TeachingSubmission.fromJson(
      Map<String, dynamic>.from(_decode(response) as Map),
    );
  }

  Future<TeachingSubmission> getStudentSubmission(String id) async {
    final response = await http.get(
      _uri('/student/submissions/$id'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return TeachingSubmission.fromJson(
      Map<String, dynamic>.from(_decode(response) as Map),
    );
  }

  // ==================== 离线模式实现 ====================
  final List<ChatConversation> _offConvs = [];
  final List<ChatGroup> _offGroups = [];
  final List<ResearchProject> _offResearchProjects = [];
  final Map<String, List<ChatMessage>> _offMsgs = {};
  int _offSeq = 0;

  String _offId() => 'off${_offSeq++}';
  String _offGroupId() => 'grp${_offSeq++}';

  ChatMessage _um(String t) =>
      ChatMessage.fromJson({'role': 'user', 'content': t});
  ChatMessage _am(String t, {String reasoning = ''}) => ChatMessage.fromJson({
    'role': 'assistant',
    'content': t,
    if (reasoning.isNotEmpty) 'reasoning': reasoning,
  });
  ChatMessage _tm(String name, String out) =>
      ChatMessage.fromJson({'role': 'tool', 'name': name, 'content': out});

  void _offlineLogin(String name) {
    sessionId = 'offline-session';
    userId = 'offline-user';
    username = name.isEmpty ? '离线用户' : name;
    email = name.contains('@') ? name : null;
    sessionExpiresAt = DateTime.now().toUtc().add(const Duration(days: 7));
    if (_offConvs.isEmpty) _seedOffline();
  }

  void _seedOffline() {
    final now = DateTime.now();
    final c1 = ChatConversation(
      id: _offId(),
      title: '线性代数 期末复习',
      updatedAt: now.subtract(const Duration(hours: 2)),
    );
    _offConvs.add(c1);
    _offMsgs[c1.id] = [
      _um('帮我复习一下特征值怎么求'),
      _am(
        '特征值满足特征方程 det(A − λI) = 0。先算出这个行列式关于 λ 的多项式 '
        '再解方程得到各 λ 就是特征值。需要我用一个 2×2 的例子带你走一遍吗？',
      ),
    ];

    final c2 = ChatConversation(
      id: _offId(),
      title: '检索我的课件 · 概率论',
      updatedAt: now.subtract(const Duration(days: 3)),
    );
    _offConvs.add(c2);
    _offMsgs[c2.id] = [];
  }

  ChatConversation _offlineNewConversation({
    WorkspaceType workspaceType = WorkspaceType.learning,
    String? researchProjectId,
    String? groupId,
  }) {
    final c = ChatConversation(
      id: _offId(),
      title: '新对话',
      updatedAt: DateTime.now(),
      workspaceType: workspaceType,
      researchProjectId: researchProjectId,
      groupId: groupId,
    );
    _offConvs.insert(0, c);
    _offMsgs[c.id] = [];
    return c;
  }

  bool _needsTool(String input) {
    final v = input.toLowerCase();
    return v.contains('检索') ||
        v.contains('课件') ||
        v.contains('rag') ||
        v.contains('资料');
  }

  Future<List<ChatMessage>> _offlineSend(String id, String content) async {
    await Future.delayed(const Duration(milliseconds: 600)); // 模拟推理耗时
    final list = _offMsgs.putIfAbsent(id, () => []);
    final result = <ChatMessage>[];
    if (_needsTool(content)) {
      result.add(
        _tm(
          'rag.search',
          'query: "$content"\ntop_k: 3\nhits:\n'
              '  - 第3章 条件概率.pdf  (score 0.87)\n'
              '  - 习题课_贝叶斯.md    (score 0.81)\n'
              '  - 期中复习提纲.docx   (score 0.74)',
        ),
      );
      result.add(
        _am(
          '我已从课件里检索到最相关的三处内容（见上方工具块）。'
          '要不要我挑其中一道例题带你走一遍？',
        ),
      );
    } else {
      result.add(
        _am(
          '（离线模式）收到：$content。接真实后端后这里会返回模型的实际回复。',
          reasoning: '先识别用户的问题类型，再结合当前对话上下文组织回答。',
        ),
      );
    }
    // 同时写入本地存储 保证切换会话后 getMessages 仍一致
    list
      ..add(_um(content))
      ..addAll(result);
    return result;
  }
}
