// ESA 后端 REST 客户端 —— 按 API.md 对齐
// Base URL 可用 --dart-define=ESA_API_BASE=http://x.x.x.x:8000 覆盖
// 认证：登录拿到 session_id 之后所有请求带 Authorization: Bearer <session_id>
//
// 当 config.dart 里 kOfflineMode == true 时 所有方法走本地假数据 完全不发网络请求

import 'dart:convert';

import 'package:http/http.dart' as http;

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

class ApiClient {
  ApiClient({String? baseUrl})
    : baseUrl =
          baseUrl ??
          const String.fromEnvironment(
            'ESA_API_BASE',
            defaultValue: 'http://115.29.197.244:51024',
          );

  final String baseUrl;

  String? sessionId;
  String? userId;
  String? username;
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
  Future<void> register(String username, String password) async {
    if (kOfflineMode) return; // 离线模式注册直接成功
    final r = await http.post(
      _uri('/auth/register'),
      headers: _headers(),
      body: jsonEncode({'username': username, 'password': password}),
    );
    if (r.statusCode != 201) _fail(r);
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
    sessionExpiresAt = DateTime.tryParse(data['expires_at'] as String? ?? '');
  }

  Future<void> logout() async {
    if (kOfflineMode) {
      sessionId = null;
      userId = null;
      username = null;
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

  // ---------- 对话 ----------
  Future<List<ChatConversation>> listConversations() async {
    if (kOfflineMode) return List.of(_offConvs);
    final r = await http.get(
      _uri('/conversations'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 200) _fail(r);
    final list = _decode(r) as List;
    return list
        .map((e) => ChatConversation.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<ChatConversation> createConversation() async {
    if (kOfflineMode) return _offlineNewConversation();
    final r = await http.post(
      _uri('/conversations'),
      headers: _headers(auth: true),
    );
    if (r.statusCode != 201) _fail(r);
    return ChatConversation.fromJson(_decode(r) as Map<String, dynamic>);
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

    String eventName = 'message';
    final dataLines = <String>[];

    await for (final line
        in response.stream
            .transform(utf8.decoder)
            .transform(const LineSplitter())) {
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

    // 兼容服务端关闭连接前没有再发送空行的情况。
    if (dataLines.isNotEmpty) {
      final decoded = jsonDecode(dataLines.join('\n'));
      if (decoded is Map<String, dynamic>) {
        yield ChatStreamEvent(eventName, decoded);
      }
    }
  }

  // ==================== 离线模式实现 ====================
  final List<ChatConversation> _offConvs = [];
  final Map<String, List<ChatMessage>> _offMsgs = {};
  int _offSeq = 0;

  String _offId() => 'off${_offSeq++}';

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

  ChatConversation _offlineNewConversation() {
    final c = ChatConversation(
      id: _offId(),
      title: '新对话',
      updatedAt: DateTime.now(),
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
