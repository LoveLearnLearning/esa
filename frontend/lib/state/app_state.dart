// ESA 应用状态 —— 集中式 ChangeNotifier
// README 建议 Riverpod 这里用 Flutter 自带的 ChangeNotifier 减少额外依赖
// 助手回复按 README 用假数据 + 流式模拟 接后端时替换 _startReply 即可

import 'dart:async';

import 'package:flutter/material.dart';

import '../models/models.dart';

class AppState extends ChangeNotifier {
  // ---- 主题与设置 ----
  ThemeMode themeMode = ThemeMode.dark; // 深色为默认主题
  bool streamOn = true; // 流式输出
  bool toolsOn = true; // 工具调用详情

  // ---- 用户 ----
  String username = '';
  String email = '';
  String role = '学生'; // 学生 / 教师

  // ---- 对话 ----
  final List<ChatConversation> conversations = [];
  final Map<String, List<ChatMessage>> _messages = {};
  String? activeId;
  bool busy = false; // 正在生成回复

  Timer? _replyTimer;
  Timer? _streamTimer;

  List<ChatMessage> get messages =>
      activeId == null ? const [] : (_messages[activeId] ?? const []);

  ChatConversation? get activeConversation {
    if (activeId == null) return null;
    for (final c in conversations) {
      if (c.id == activeId) return c;
    }
    return null;
  }

  String _newId() => DateTime.now().microsecondsSinceEpoch.toString();

  // ---- 会话生命周期 ----
  void login(String name, {String mail = ''}) {
    username = name;
    email = mail.isEmpty ? '$name@esa.study' : mail;
    _seedDemoConversations();
    newConversation(); // 登录后进入一个空对话 显示欢迎空状态
  }

  void logout() {
    _replyTimer?.cancel();
    _streamTimer?.cancel();
    conversations.clear();
    _messages.clear();
    activeId = null;
    busy = false;
    username = '';
    email = '';
    notifyListeners();
  }

  void _seedDemoConversations() {
    final now = DateTime.now();
    void add(String title, DateTime at, {bool pinned = false}) {
      final id = _newId();
      conversations.add(
        ChatConversation(id: id, title: title, updatedAt: at, pinned: pinned),
      );
      _messages[id] = [];
    }

    add('线性代数 期末复习', now.subtract(const Duration(hours: 2)), pinned: true);
    add('讲讲牛顿第二定律', now.subtract(const Duration(hours: 5)));
    add('生成一周复习计划', now.subtract(const Duration(hours: 9)));
    add('检索我的课件 · 概率论', now.subtract(const Duration(days: 3)));
    add('英语作文批改', now.subtract(const Duration(days: 12)));
  }

  void setActive(String id) {
    if (activeId == id) return;
    _stopGenerating();
    activeId = id;
    notifyListeners();
  }

  void newConversation() {
    _stopGenerating();
    final id = _newId();
    conversations.insert(
      0,
      ChatConversation(id: id, title: '新对话', updatedAt: DateTime.now()),
    );
    _messages[id] = [];
    activeId = id;
    notifyListeners();
  }

  void renameConversation(String id, String title) {
    final t = title.trim();
    if (t.isEmpty) return;
    for (final c in conversations) {
      if (c.id == id) {
        c.title = t;
        break;
      }
    }
    notifyListeners();
  }

  void deleteConversation(String id) {
    conversations.removeWhere((c) => c.id == id);
    _messages.remove(id);
    if (activeId == id) {
      _stopGenerating();
      activeId = conversations.isNotEmpty ? conversations.first.id : null;
    }
    notifyListeners();
  }

  void togglePin(String id) {
    for (final c in conversations) {
      if (c.id == id) {
        c.pinned = !c.pinned;
        break;
      }
    }
    notifyListeners();
  }

  // ---- 设置 ----
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

  void setRole(String v) {
    role = v;
    notifyListeners();
  }

  void updateProfile({String? name, String? mail, String? roleValue}) {
    if (name != null && name.trim().isNotEmpty) username = name.trim();
    if (mail != null) email = mail.trim();
    if (roleValue != null) role = roleValue;
    notifyListeners();
  }

  // ---- 发送与回复 ----
  void send(String text) {
    final input = text.trim();
    if (input.isEmpty || busy) return;
    if (activeId == null) newConversation();
    final id = activeId!;
    final list = _messages[id]!;

    list.add(ChatMessage(id: _newId(), role: MessageRole.user, text: input));

    // 首条消息用输入内容作为标题
    final conv = activeConversation;
    if (conv != null) {
      conv.updatedAt = DateTime.now();
      if (conv.title == '新对话') {
        conv.title = input.length > 18 ? '${input.substring(0, 18)}…' : input;
      }
    }
    notifyListeners();

    _startReply(id, input);
  }

  void regenerate(String assistantMessageId) {
    final id = activeId;
    if (id == null || busy) return;
    final list = _messages[id]!;
    final index = list.indexWhere((m) => m.id == assistantMessageId);
    if (index < 0) return;
    // 找到该助手消息之前最近的一条用户消息
    String? prompt;
    for (var i = index - 1; i >= 0; i--) {
      if (list[i].isUser) {
        prompt = list[i].text;
        break;
      }
    }
    if (prompt == null) return;
    list.removeRange(index, list.length);
    notifyListeners();
    Future.delayed(const Duration(milliseconds: 250), () {
      if (activeId == id) _startReply(id, prompt!);
    });
  }

  void _startReply(String convId, String input) {
    busy = true;
    notifyListeners();

    _replyTimer = Timer(const Duration(milliseconds: 420), () {
      if (activeId != convId) return;
      final list = _messages[convId]!;
      final reply = ChatMessage(
        id: _newId(),
        role: MessageRole.assistant,
        typing: true,
        tool: (toolsOn && _needsTool(input)) ? _demoTool(input) : null,
      );
      list.add(reply);
      notifyListeners();

      final target = _replyFor(input);
      if (!streamOn) {
        reply.text = target;
        reply.typing = false;
        busy = false;
        notifyListeners();
        return;
      }

      var cursor = 0;
      _streamTimer = Timer.periodic(const Duration(milliseconds: 26), (t) {
        if (activeId != convId) {
          t.cancel();
          return;
        }
        cursor = (cursor + 3).clamp(0, target.length);
        reply.text = target.substring(0, cursor);
        if (cursor >= target.length) {
          reply.typing = false;
          busy = false;
          t.cancel();
        }
        notifyListeners();
      });
    });
  }

  void _stopGenerating() {
    _replyTimer?.cancel();
    _streamTimer?.cancel();
    if (busy) {
      // 结束当前正在输出的消息的光标
      final list = activeId == null ? null : _messages[activeId];
      if (list != null && list.isNotEmpty && list.last.typing) {
        list.last.typing = false;
      }
      busy = false;
    }
  }

  bool _needsTool(String input) {
    final v = input.toLowerCase();
    return v.contains('检索') ||
        v.contains('课件') ||
        v.contains('rag') ||
        v.contains('资料');
  }

  ToolInvocation _demoTool(String input) {
    return ToolInvocation(
      name: 'rag.search',
      durationMs: 480,
      output: 'query: "$input"\n'
          'top_k: 3\n'
          'hits:\n'
          '  - 第3章 条件概率.pdf  (score 0.87)\n'
          '  - 习题课_贝叶斯.md    (score 0.81)\n'
          '  - 期中复习提纲.docx   (score 0.74)',
    );
  }

  String _replyFor(String input) {
    final v = input.toLowerCase();
    if (v.contains('计划')) {
      return '好的，我为你安排一周复习计划：\n'
          '周一至周三主攻薄弱章节，每天两个番茄钟；'
          '周四做一套综合卷并订正；周五整理错题；周末回顾记忆卡片。'
          '需要我把它拆成每日清单吗？';
    }
    if (v.contains('批改') || v.contains('作文') || v.contains('作业')) {
      return '把题目和你的作答发给我即可。我会先指出关键错误，再给出订正思路和一个更规范的范例，'
          '最后总结这一类题的通用方法。';
    }
    if (_needsTool(input)) {
      return '我已从你的课件里检索到最相关的三处内容（见上方工具块）。'
          '概括来说：条件概率的核心是缩小样本空间，贝叶斯公式则是在此基础上做“原因反推”。'
          '要不要我用其中一道例题带你走一遍？';
    }
    return '收到。我可以帮你讲解题目、制定复习计划、检索课件或批改作业。'
        '告诉我你现在卡在哪一步，我们一步步来。';
  }

  @override
  void dispose() {
    _replyTimer?.cancel();
    _streamTimer?.cancel();
    super.dispose();
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
