// ESA 应用状态 —— 集中式 ChangeNotifier 通过 ApiClient 调用真实后端
// 认证 / 对话列表 / 历史消息 / 发消息 均对接 API.md 定义的接口
// 置顶(pinned) 主题 设置为纯前端本地状态 后端无对应字段

import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../models/models.dart';

class AppState extends ChangeNotifier {
  AppState({ApiClient? api}) : api = api ?? ApiClient();

  final ApiClient api;

  // ---- 本地设置(不落后端) ----
  ThemeMode themeMode = ThemeMode.dark;
  bool streamOn = true;
  bool toolsOn = true;
  String email = '';
  String role = '学生';

  // ---- 对话数据 ----
  final List<ChatConversation> conversations = [];
  final Map<String, List<ChatMessage>> _messages = {};
  final Set<String> _pinned = {}; // 本地置顶集合
  String? activeId;

  bool busy = false; // 正在发消息
  bool loadingConversations = false;
  bool loadingMessages = false;

  String get username => api.username ?? '';
  bool get isLoggedIn => api.isLoggedIn;

  List<ChatMessage> get messages =>
      activeId == null ? const [] : (_messages[activeId] ?? const []);

  ChatConversation? get activeConversation {
    if (activeId == null) return null;
    for (final c in conversations) {
      if (c.id == activeId) return c;
    }
    return null;
  }

  // ============ 认证 ============
  /// 返回 null 表示成功 否则返回错误文案
  Future<String?> login(String username, String password) async {
    try {
      await api.login(username, password);
      email = '$username@esa.study';
      await _afterLogin();
      return null;
    } on ApiException catch (e) {
      return e.detail;
    } catch (_) {
      return '无法连接服务器 请检查后端是否启动';
    }
  }

  /// 注册并自动登录 返回 null 表示成功 否则返回错误文案
  Future<String?> register(String username, String password) async {
    try {
      await api.register(username, password);
      await api.login(username, password);
      email = '$username@esa.study';
      await _afterLogin();
      return null;
    } on ApiException catch (e) {
      return e.detail;
    } catch (_) {
      return '无法连接服务器 请检查后端是否启动';
    }
  }

  Future<void> _afterLogin() async {
    await loadConversations();
    if (conversations.isNotEmpty) {
      await setActive(conversations.first.id);
    } else {
      activeId = null;
    }
    notifyListeners();
  }

  Future<void> logout() async {
    await api.logout();
    _clearSession();
  }

  void _clearSession() {
    api.sessionId = null;
    api.userId = null;
    api.username = null;
    conversations.clear();
    _messages.clear();
    _pinned.clear();
    activeId = null;
    busy = false;
    notifyListeners();
  }

  /// 统一处理 401 会话失效 直接回登录页
  bool _handled401(Object e) {
    if (e is ApiException && e.isUnauthorized) {
      _clearSession();
      return true;
    }
    return false;
  }

  // ============ 对话 ============
  Future<void> loadConversations() async {
    loadingConversations = true;
    notifyListeners();
    try {
      final list = await api.listConversations();
      for (final c in list) {
        c.pinned = _pinned.contains(c.id);
      }
      conversations
        ..clear()
        ..addAll(list);
    } catch (e) {
      if (!_handled401(e)) rethrow;
    } finally {
      loadingConversations = false;
      notifyListeners();
    }
  }

  Future<void> setActive(String id) async {
    activeId = id;
    notifyListeners();
    if (!_messages.containsKey(id)) {
      await _loadMessages(id);
    }
  }

  Future<void> _loadMessages(String id) async {
    loadingMessages = true;
    notifyListeners();
    try {
      final msgs = await api.getMessages(id);
      _messages[id] = msgs;
    } catch (e) {
      if (_handled401(e)) return;
      _messages[id] = [];
    } finally {
      loadingMessages = false;
      notifyListeners();
    }
  }

  Future<void> newConversation() async {
    try {
      final conv = await api.createConversation();
      conversations.insert(0, conv);
      _messages[conv.id] = [];
      activeId = conv.id;
      notifyListeners();
    } catch (e) {
      if (!_handled401(e)) rethrow;
    }
  }

  Future<void> renameConversation(String id, String title) async {
    final t = title.trim();
    if (t.isEmpty) return;
    for (final c in conversations) {
      if (c.id == id) c.title = t;
    }
    notifyListeners();
    try {
      await api.renameConversation(id, t);
    } catch (e) {
      if (!_handled401(e)) rethrow;
    }
  }

  Future<void> deleteConversation(String id) async {
    try {
      await api.deleteConversation(id);
    } catch (e) {
      if (_handled401(e)) return;
      rethrow;
    }
    conversations.removeWhere((c) => c.id == id);
    _messages.remove(id);
    _pinned.remove(id);
    if (activeId == id) {
      activeId = conversations.isNotEmpty ? conversations.first.id : null;
      if (activeId != null && !_messages.containsKey(activeId)) {
        await _loadMessages(activeId!);
      }
    }
    notifyListeners();
  }

  void togglePin(String id) {
    if (_pinned.contains(id)) {
      _pinned.remove(id);
    } else {
      _pinned.add(id);
    }
    for (final c in conversations) {
      if (c.id == id) c.pinned = _pinned.contains(id);
    }
    notifyListeners();
  }

  // ============ 发送消息 ============
  Future<void> send(String text) async {
    final input = text.trim();
    if (input.isEmpty || busy) return;

    // 没有活动对话时先建一个
    if (activeId == null) {
      await newConversation();
      if (activeId == null) return; // 建失败
    }
    final id = activeId!;
    final list = _messages.putIfAbsent(id, () => []);

    list.add(ChatMessage.user(input));
    _touchConversation(id, input);

    final placeholder = ChatMessage.typingPlaceholder();
    list.add(placeholder);
    busy = true;
    notifyListeners();

    try {
      final newMsgs = await api.sendMessage(id, input);
      list.remove(placeholder);
      // 后端返回里包含用户消息本身 已乐观添加过 这里跳过
      list.addAll(newMsgs.where((m) => m.role != MessageRole.user));
    } catch (e) {
      list.remove(placeholder);
      if (_handled401(e)) return;
      final detail = e is ApiException ? e.detail : '无法连接服务器 请检查后端是否启动';
      list.add(ChatMessage(
        id: DateTime.now().microsecondsSinceEpoch.toString(),
        role: MessageRole.assistant,
        text: '（出错了：$detail）',
      ));
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  void regenerate(String assistantMessageId) {
    final id = activeId;
    if (id == null || busy) return;
    final list = _messages[id];
    if (list == null) return;
    final index = list.indexWhere((m) => m.id == assistantMessageId);
    if (index < 0) return;
    String? prompt;
    for (var i = index - 1; i >= 0; i--) {
      if (list[i].isUser) {
        prompt = list[i].text;
        break;
      }
    }
    if (prompt != null) send(prompt);
  }

  void _touchConversation(String id, String firstInput) {
    final conv = activeConversation;
    if (conv == null || conv.id != id) return;
    conv.updatedAt = DateTime.now();
    if (conv.title == '新对话') {
      final title =
          firstInput.length > 18 ? '${firstInput.substring(0, 18)}…' : firstInput;
      conv.title = title;
      // 持久化标题 忽略结果
      api.renameConversation(id, title).catchError((_) {});
    }
  }

  // ============ 设置 ============
  void setThemeMode(ThemeMode mode) {
    themeMode = mode;
    notifyListeners();
  }

  void setStreamOn(bool v) {
    streamOn = v;
    notifyListeners();
  }

  void setToolsOn(bool v) {
    toolsOn = v;
    notifyListeners();
  }

  void updateProfile({String? name, String? mail, String? roleValue}) {
    if (name != null && name.trim().isNotEmpty) api.username = name.trim();
    if (mail != null) email = mail.trim();
    if (roleValue != null) role = roleValue;
    notifyListeners();
  }
}

/// 通过 InheritedNotifier 把 AppState 传给整棵子树
class AppScope extends InheritedNotifier<AppState> {
  const AppScope({super.key, required AppState state, required super.child})
      : super(notifier: state);

  static AppState of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<AppScope>();
    assert(scope != null, 'AppScope not found in widget tree');
    return scope!.notifier!;
  }
}
