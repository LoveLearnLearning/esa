// ESA 后端 REST 客户端 —— 按 API.md 对齐
// Base URL 可用 --dart-define=ESA_API_BASE=https://example.com/api 覆盖
// 认证：登录拿到 session_id 之后所有请求带 Authorization: Bearer <session_id>
//
// 当 config.dart 里 kOfflineMode == true 时 所有方法走本地假数据 完全不发网络请求

import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';
import 'package:flutter/foundation.dart' show kIsWeb;

import '../config.dart';
import '../models/hust_import_models.dart';
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

class CodeExecutionResult {
  const CodeExecutionResult({
    required this.ok,
    required this.language,
    required this.code,
    required this.codeChanged,
    required this.dependencies,
    required this.rejectedDependencies,
    required this.notes,
    required this.warnings,
    required this.modelUsed,
    required this.attemptCount,
    required this.result,
    required this.installResults,
  });

  factory CodeExecutionResult.fromJson(Map<String, dynamic> json) =>
      CodeExecutionResult(
        ok: json['ok'] == true,
        language: json['language']?.toString() ?? 'plaintext',
        code: json['code']?.toString() ?? '',
        codeChanged: json['code_changed'] == true,
        dependencies: _stringValues(json['dependencies']),
        rejectedDependencies: _stringValues(json['rejected_dependencies']),
        notes: _stringValues(json['notes']),
        warnings: _stringValues(json['warnings']),
        modelUsed: json['model_used'] == true,
        attemptCount: (json['attempt_count'] as num?)?.toInt() ?? 0,
        result: json['result'] is Map
            ? Map<String, dynamic>.from(json['result'] as Map)
            : const {},
        installResults: json['install_results'] is List
            ? (json['install_results'] as List)
                  .whereType<Map>()
                  .map(Map<String, dynamic>.from)
                  .toList()
            : const [],
      );

  static List<String> _stringValues(Object? value) => value is List
      ? value.whereType<Object>().map((item) => item.toString()).toList()
      : const [];

  final bool ok;
  final String language;
  final String code;
  final bool codeChanged;
  final List<String> dependencies;
  final List<String> rejectedDependencies;
  final List<String> notes;
  final List<String> warnings;
  final bool modelUsed;
  final int attemptCount;
  final Map<String, dynamic> result;
  final List<Map<String, dynamic>> installResults;

  String get stdout => result['stdout']?.toString() ?? '';
  String get stderr => result['stderr']?.toString() ?? '';
  String get error => result['error']?.toString() ?? '';
  double get durationSeconds {
    final seconds = result['duration_seconds'];
    if (seconds is num) return seconds.toDouble();
    final milliseconds = result['duration_ms'];
    return milliseconds is num ? milliseconds.toDouble() / 1000 : 0;
  }
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

class RequestCancellation {
  bool _cancelled = false;
  void Function()? _activeCancel;

  bool get isCancelled => _cancelled;

  void cancel() {
    if (_cancelled) return;
    _cancelled = true;
    _activeCancel?.call();
    _activeCancel = null;
  }

  void attach(void Function() callback) {
    if (_cancelled) {
      callback();
    } else {
      _activeCancel = callback;
    }
  }

  void detach() => _activeCancel = null;
}

class AttachmentTransfer {
  AttachmentTransfer._({
    required http.Client client,
    required http.StreamedResponse response,
    required this.mediaType,
    required this.filename,
  }) : contentLength = response.contentLength {
    _client = client;
    chunks = _closeAfter(response.stream);
  }

  late final http.Client _client;
  late final Stream<List<int>> chunks;
  final int? contentLength;
  final String mediaType;
  final String filename;
  bool _closed = false;

  Stream<List<int>> _closeAfter(Stream<List<int>> source) async* {
    try {
      await for (final chunk in source) {
        yield chunk;
      }
    } finally {
      cancel();
    }
  }

  void cancel() {
    if (_closed) return;
    _closed = true;
    _client.close();
  }
}

class KnowledgeBaseUploadFile {
  const KnowledgeBaseUploadFile({
    required this.filename,
    required this.stream,
    required this.length,
  });

  final String filename;
  final Stream<List<int>> stream;
  final int length;
}

class ApiClient {
  ApiClient({String? baseUrl, http.Client Function()? clientFactory})
    : baseUrl = _normalizeBaseUrl(baseUrl ?? _defaultBaseUrl),
      _clientFactory = clientFactory ?? http.Client.new;

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
  final http.Client Function() _clientFactory;

  static const int _personalPreviewMaxBytes = 8 * 1024 * 1024;
  static const int _personalPreviewCacheMaxBytes = 24 * 1024 * 1024;
  final LinkedHashMap<String, AttachmentContent> _personalPreviewCache =
      LinkedHashMap<String, AttachmentContent>();
  int _personalPreviewCacheBytes = 0;
  String? _personalPreviewCacheOwner;

  String? sessionId;
  String? userId;
  String? username;
  String? email;
  String accountRole = 'student';
  DateTime? sessionExpiresAt;

  bool get isLoggedIn => sessionId != null;

  /// 教务密码只能发往 HTTPS，或明确的本机开发地址。
  /// 临时联调可用 --dart-define=ESA_ALLOW_INSECURE_CREDENTIALS=true 覆盖。
  bool get allowsCredentialSubmission {
    const allowInsecure = bool.fromEnvironment(
      'ESA_ALLOW_INSECURE_CREDENTIALS',
      defaultValue: false,
    );
    if (allowInsecure) return true;
    final configuredUri = Uri.tryParse(baseUrl);
    if (configuredUri == null) return false;
    // Flutter Web 默认使用同源相对地址 `/api`。它的实际传输协议由当前
    // 页面决定，因此必须先解析到页面来源，不能把生产 HTTPS 误判为明文。
    final uri = configuredUri.hasScheme
        ? configuredUri
        : kIsWeb
        ? Uri.base.resolveUri(configuredUri)
        : configuredUri;
    if (uri.scheme.toLowerCase() == 'https') return true;
    return const {
      'localhost',
      '127.0.0.1',
      '::1',
      '10.0.2.2',
      'host.docker.internal',
    }.contains(uri.host.toLowerCase());
  }

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
      clearPersonalKnowledgeBasePreviewCache();
      return;
    }
    if (sessionId == null) {
      clearPersonalKnowledgeBasePreviewCache();
      return;
    }
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
      clearPersonalKnowledgeBasePreviewCache();
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
      'doc' => 'application/msword',
      'pptx' =>
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      'ppt' => 'application/vnd.ms-powerpoint',
      'xlsx' =>
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'xls' => 'application/vnd.ms-excel',
      'csv' => 'text/csv',
      'txt' => 'text/plain',
      'md' => 'text/markdown',
      'json' => 'application/json',
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
        importedCount: (data['imported_count'] as num?)?.toInt(),
        warnings: (data['warnings'] as List? ?? const [])
            .map((item) => item.toString())
            .toList(),
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

  Future<HustImportChallenge> startHustImport() async {
    if (!allowsCredentialSubmission) {
      throw ApiException(400, '当前后端不是 HTTPS，已阻止发送教务密码。请改用 HTTPS 或本机后端。');
    }
    final r = await http.post(
      _uri('/me/schedule/import/hust/challenge'),
      headers: _headers(auth: true),
      body: '{}',
    );
    if (r.statusCode != 200 && r.statusCode != 201) _fail(r);
    return HustImportChallenge.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<ScheduleImportResult> completeHustImport({
    required String challengeId,
    required String username,
    required String password,
    required String captcha,
    required String semesterName,
    required DateTime startDate,
    required DateTime endDate,
    bool toNewTable = false,
    String? newTableName,
  }) async {
    if (!allowsCredentialSubmission) {
      throw ApiException(400, '当前后端不是 HTTPS，已阻止发送教务密码。请改用 HTTPS 或本机后端。');
    }
    final r = await http.post(
      _uri('/me/schedule/import/hust/complete'),
      headers: _headers(auth: true),
      body: jsonEncode({
        'challenge_id': challengeId,
        'username': username,
        'password': password,
        'captcha': captcha,
        'semester_name': semesterName,
        'start_date': _dateOnly(startDate),
        'end_date': _dateOnly(endDate),
        'target': toNewTable ? 'new' : 'current',
        if (toNewTable && newTableName?.trim().isNotEmpty == true)
          'table_name': newTableName!.trim(),
      }),
    );
    if (r.statusCode != 200) _fail(r);
    final data = _decode(r) as Map<String, dynamic>;
    final courses = (data['courses'] as List? ?? const [])
        .whereType<Map>()
        .map((item) => ScheduleCourse.fromJson(Map<String, dynamic>.from(item)))
        .toList();
    return ScheduleImportResult(
      courses: courses,
      skippedCount:
          (data['skipped_count'] as num?)?.toInt() ??
          (data['skipped_entries'] as num?)?.toInt() ??
          0,
      importedCount:
          (data['imported_count'] as num?)?.toInt() ??
          (data['imported_entries'] as num?)?.toInt() ??
          courses.length,
      warnings: (data['warnings'] as List? ?? const [])
          .map((item) => item.toString())
          .toList(),
    );
  }

  String _dateOnly(DateTime date) {
    String two(int value) => value.toString().padLeft(2, '0');
    return '${date.year}-${two(date.month)}-${two(date.day)}';
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
      _uri('/me/core-memories'),
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
    String scopeType = 'global',
    WorkspaceType? workspaceType,
  }) async {
    final r = await http.post(
      _uri('/me/core-memories'),
      headers: _headers(auth: true),
      body: jsonEncode({
        'memory_key': key,
        'content': content,
        'category': category,
        'scope_type': scopeType,
        'workspace_type': ?workspaceType?.wireName,
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

  Future<void> forgetCoreMemory(String memoryId) async {
    final r = await http.delete(
      _uri('/me/core-memories/${Uri.encodeComponent(memoryId)}'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 204) _fail(r);
  }

  Future<CoreMemoryItem> setCoreMemorySuppressed(
    String memoryId, {
    required bool suppressed,
  }) async {
    final action = suppressed ? 'suppress' : 'restore';
    final r = await http.post(
      _uri('/me/core-memories/${Uri.encodeComponent(memoryId)}/$action'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    return CoreMemoryItem.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<List<Map<String, dynamic>>> listCoreMemoryVersions(
    String memoryId,
  ) async {
    final r = await http.get(
      _uri('/me/core-memories/${Uri.encodeComponent(memoryId)}/versions'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    return (_decode(r) as List)
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  Future<List<MemoryCandidateItem>> listMemoryCandidates() async {
    final r = await http.get(
      _uri('/me/memory-candidates'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    return (_decode(r) as List)
        .whereType<Map>()
        .map(
          (item) =>
              MemoryCandidateItem.fromJson(Map<String, dynamic>.from(item)),
        )
        .toList();
  }

  Future<void> decideMemoryCandidate(
    String candidateId, {
    required bool accept,
    String? content,
    String? category,
    String? scopeType,
    WorkspaceType? workspaceType,
  }) async {
    final action = accept ? 'accept' : 'reject';
    final r = await http.post(
      _uri('/me/memory-candidates/${Uri.encodeComponent(candidateId)}/$action'),
      headers: _headers(auth: true),
      body: accept
          ? jsonEncode({
              'content': ?content,
              'category': ?category,
              'scope_type': ?scopeType,
              'workspace_type': ?workspaceType?.wireName,
            })
          : null,
    );
    if (accept ? r.statusCode != 200 : r.statusCode != 204) _fail(r);
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

  Future<ChatConversation> getConversation(String id) async {
    if (kOfflineMode) {
      return _offConvs.firstWhere((conversation) => conversation.id == id);
    }
    final response = await http.get(
      _uri('/conversations/${Uri.encodeComponent(id)}'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return ChatConversation.fromJson(_decode(response) as Map<String, dynamic>);
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
    String? classId,
    String? assignmentId,
    String? groupId,
  }) async {
    if (workspace == WorkspaceType.learning && researchProjectId == null) {
      return createConversation(groupId: groupId);
    }
    if (kOfflineMode) {
      return _offlineNewConversation(
        workspaceType: workspace,
        researchProjectId: researchProjectId,
        classId: classId,
        assignmentId: assignmentId,
        groupId: groupId,
      );
    }
    final body = <String, String>{'workspace_type': workspace.wireName};
    if (researchProjectId case final projectId?) {
      body['research_project_id'] = projectId;
    }
    if (classId case final selectedClassId?) {
      body['class_id'] = selectedClassId;
    }
    if (assignmentId case final selectedAssignmentId?) {
      body['assignment_id'] = selectedAssignmentId;
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

  Future<ResearchProjectProfile> getResearchProjectProfile(
    String projectId,
  ) async {
    final r = await http.get(
      _uri('/research/projects/${Uri.encodeComponent(projectId)}/profile'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    return ResearchProjectProfile.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<ResearchProjectProfile> saveResearchProjectProfile(
    String projectId, {
    required String instructions,
    required int expectedRevision,
  }) async {
    final r = await http.put(
      _uri('/research/projects/${Uri.encodeComponent(projectId)}/profile'),
      headers: _headers(auth: true),
      body: jsonEncode({
        'agent_instructions': instructions,
        'expected_revision': expectedRevision,
      }),
    );
    if (r.statusCode != 200) _fail(r);
    return ResearchProjectProfile.fromJson(_decode(r) as Map<String, dynamic>);
  }

  Future<List<AgentActionItem>> listAgentActions({String? status}) async {
    final query = status == null
        ? ''
        : '?status=${Uri.encodeQueryComponent(status)}';
    final response = await http.get(
      _uri('/me/agent-actions$query'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return (_decode(response) as List)
        .map((item) => AgentActionItem.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<AgentActionItem> decideAgentAction(
    String actionId, {
    required bool approve,
  }) async {
    final decision = approve ? 'approve' : 'reject';
    final response = await http.post(
      _uri('/me/agent-actions/${Uri.encodeComponent(actionId)}/$decision'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return AgentActionItem.fromJson(_decode(response) as Map<String, dynamic>);
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
    return ResearchDocument.fromJson(_decode(response) as Map<String, dynamic>);
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
      mediaType: response.headers['content-type'] ?? attachment.mediaType,
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

  Future<CodeExecutionResult> executeCode(
    String conversationId, {
    required String code,
    required String language,
  }) async {
    if (kOfflineMode) {
      return CodeExecutionResult.fromJson({
        'ok': false,
        'language': language,
        'code': code,
        'code_changed': false,
        'warnings': ['离线模式未启用沙箱'],
        'result': {'ok': false, 'error': 'sandbox_disabled'},
      });
    }
    final response = await http.post(
      _uri('/conversations/$conversationId/code/execute'),
      headers: _headers(auth: true),
      body: jsonEncode({'code': code, 'language': language}),
    );
    if (response.statusCode != 200) _fail(response);
    return CodeExecutionResult.fromJson(
      _decode(response) as Map<String, dynamic>,
    );
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

  // ---------- 个人知识库 ----------
  Future<PersonalKnowledgeBase> getPersonalKnowledgeBase() async {
    if (kOfflineMode) return const PersonalKnowledgeBase.empty();
    final response = await http.get(
      _uri('/me/knowledge-base'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return PersonalKnowledgeBase.fromJson(
      Map<String, dynamic>.from(_decode(response) as Map),
    );
  }

  Future<PersonalKnowledgeBase> uploadPersonalKnowledgeBaseFiles(
    List<KnowledgeBaseUploadFile> files,
  ) async {
    if (files.isEmpty) return getPersonalKnowledgeBase();
    if (kOfflineMode) return const PersonalKnowledgeBase.empty();
    final request = http.MultipartRequest(
      'POST',
      _uri('/me/knowledge-base/files'),
    );
    if (sessionId != null) {
      request.headers['Authorization'] = 'Bearer $sessionId';
    }
    for (final file in files) {
      request.files.add(
        http.MultipartFile(
          'files',
          file.stream,
          file.length,
          filename: file.filename,
          contentType: MediaType.parse(_mimeFor(file.filename, Uint8List(0))),
        ),
      );
    }
    try {
      final streamed = await request.send().timeout(
        const Duration(minutes: 15),
      );
      final response = await http.Response.fromStream(
        streamed,
      ).timeout(const Duration(minutes: 2));
      if (response.statusCode != 202) _fail(response);
      return PersonalKnowledgeBase.fromJson(
        Map<String, dynamic>.from(_decode(response) as Map),
      );
    } on TimeoutException {
      throw ApiException(0, '文件上传超时，请稍后重试');
    } on http.ClientException {
      throw ApiException(0, '网络异常，请检查网络后重试');
    }
  }

  Future<AttachmentTransfer> fetchPersonalKnowledgeBaseFile(
    KnowledgeBaseFile file, {
    bool download = false,
    String? range,
    RequestCancellation? cancellation,
  }) => _openPersonalKnowledgeBaseTransfer(
    file,
    endpoint: download ? 'download' : 'content',
    range: range,
    cancellation: cancellation,
  );

  Future<AttachmentContent> fetchPersonalKnowledgeBasePreview(
    KnowledgeBaseFile file, {
    RequestCancellation? cancellation,
  }) async {
    final owner = userId ?? '';
    if (_personalPreviewCacheOwner != owner) {
      clearPersonalKnowledgeBasePreviewCache();
      _personalPreviewCacheOwner = owner;
    }
    final cacheKey = '$owner:${file.id}';
    final cached = _personalPreviewCache.remove(cacheKey);
    if (cached != null) {
      _personalPreviewCache[cacheKey] = cached;
      return cached;
    }
    final transfer = await _openPersonalKnowledgeBaseTransfer(
      file,
      endpoint: 'preview',
      cancellation: cancellation,
    );
    cancellation?.attach(transfer.cancel);
    if (cancellation?.isCancelled ?? false) {
      throw ApiException(0, '预览请求已取消');
    }
    final declared = transfer.contentLength;
    if (declared != null && declared > _personalPreviewMaxBytes) {
      transfer.cancel();
      cancellation?.detach();
      throw ApiException(413, '预览派生文件超过客户端安全限制');
    }
    final builder = BytesBuilder(copy: false);
    var received = 0;
    try {
      await for (final chunk in transfer.chunks) {
        received += chunk.length;
        if (received > _personalPreviewMaxBytes) {
          transfer.cancel();
          throw ApiException(413, '预览派生文件超过客户端安全限制');
        }
        builder.add(chunk);
      }
    } on http.ClientException {
      if (cancellation?.isCancelled ?? false) {
        throw ApiException(0, '预览请求已取消');
      }
      throw ApiException(0, '预览传输中断，请重试');
    } finally {
      cancellation?.detach();
      transfer.cancel();
    }
    if (cancellation?.isCancelled ?? false) {
      throw ApiException(0, '预览请求已取消');
    }
    final content = AttachmentContent(
      bytes: builder.takeBytes(),
      mediaType: transfer.mediaType,
      filename: transfer.filename,
    );
    _personalPreviewCache[cacheKey] = content;
    _personalPreviewCacheBytes += content.bytes.length;
    while (_personalPreviewCacheBytes > _personalPreviewCacheMaxBytes &&
        _personalPreviewCache.isNotEmpty) {
      final oldest = _personalPreviewCache.keys.first;
      _personalPreviewCacheBytes -= _personalPreviewCache
          .remove(oldest)!
          .bytes
          .length;
    }
    return content;
  }

  Future<AttachmentTransfer> _openPersonalKnowledgeBaseTransfer(
    KnowledgeBaseFile file, {
    required String endpoint,
    String? range,
    RequestCancellation? cancellation,
  }) async {
    final client = _clientFactory();
    cancellation?.attach(client.close);
    if (cancellation?.isCancelled ?? false) {
      throw ApiException(0, '文件请求已取消');
    }
    final request = http.Request(
      'GET',
      _uri(
        '/me/knowledge-base/files/${Uri.encodeComponent(file.id)}/$endpoint',
      ),
    );
    if (sessionId != null) {
      request.headers['Authorization'] = 'Bearer $sessionId';
    }
    if (range != null && range.trim().isNotEmpty) {
      request.headers['Range'] = range.trim();
    }
    try {
      final response = await client
          .send(request)
          .timeout(const Duration(seconds: 30));
      if (response.statusCode != 200 && response.statusCode != 206) {
        final body = BytesBuilder(copy: false);
        var total = 0;
        await for (final chunk in response.stream) {
          if (total < 64 * 1024) {
            final retained = chunk.take(64 * 1024 - total).toList();
            body.add(retained);
            total += retained.length;
          }
          if (total >= 64 * 1024) break;
        }
        _fail(
          http.Response.bytes(
            body.takeBytes(),
            response.statusCode,
            headers: response.headers,
          ),
        );
      }
      final transfer = AttachmentTransfer._(
        client: client,
        response: response,
        mediaType: response.headers['content-type'] ?? file.mediaType,
        filename: file.filename,
      );
      cancellation?.attach(transfer.cancel);
      return transfer;
    } on TimeoutException {
      client.close();
      cancellation?.detach();
      throw ApiException(0, '文件请求超时，请重试');
    } on http.ClientException {
      client.close();
      cancellation?.detach();
      if (cancellation?.isCancelled ?? false) {
        throw ApiException(0, '文件请求已取消');
      }
      throw ApiException(0, '网络异常，请检查网络后重试');
    } catch (_) {
      client.close();
      cancellation?.detach();
      rethrow;
    }
  }

  void clearPersonalKnowledgeBasePreviewCache() {
    _personalPreviewCache.clear();
    _personalPreviewCacheBytes = 0;
    _personalPreviewCacheOwner = null;
  }

  Future<void> deletePersonalKnowledgeBaseFile(String fileId) async {
    final response = await http.delete(
      _uri('/me/knowledge-base/files/${Uri.encodeComponent(fileId)}'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 204 && response.statusCode != 404) {
      _fail(response);
    }
  }

  Future<PersonalKnowledgeBase> rebuildPersonalKnowledgeBase() async {
    final response = await http.post(
      _uri('/me/knowledge-base/rebuild'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 202) _fail(response);
    return PersonalKnowledgeBase.fromJson(
      Map<String, dynamic>.from(_decode(response) as Map),
    );
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

  Future<Map<String, dynamic>> getTeachingStudent(
    String classId,
    String studentId,
  ) async {
    final response = await http.get(
      _uri('/teaching/classes/$classId/students/$studentId'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 200) _fail(response);
    return Map<String, dynamic>.from(_decode(response) as Map);
  }

  Future<void> removeTeachingStudent(String classId, String studentId) async {
    final response = await http.delete(
      _uri('/teaching/classes/$classId/members/$studentId'),
      headers: _headers(auth: true),
    );
    if (response.statusCode != 204) _fail(response);
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
    String? classId,
    String? assignmentId,
    String? groupId,
  }) {
    final c = ChatConversation(
      id: _offId(),
      title: '新对话',
      updatedAt: DateTime.now(),
      workspaceType: workspaceType,
      researchProjectId: researchProjectId,
      classId: classId,
      assignmentId: assignmentId,
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
