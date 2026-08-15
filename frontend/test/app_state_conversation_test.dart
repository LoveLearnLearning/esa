import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/state/app_state.dart';

class _ConversationApi extends ApiClient {
  _ConversationApi() : super(baseUrl: 'http://test.invalid');

  int createCalls = 0;
  final List<String> deleteCalls = [];

  @override
  Future<ChatConversation> createConversation({String? groupId}) async {
    createCalls++;
    return ChatConversation(
      id: 'conversation-$createCalls',
      title: '新对话',
      updatedAt: DateTime(2026),
      groupId: groupId,
    );
  }

  @override
  Future<void> renameConversation(String id, String title) async {}

  @override
  Future<void> deleteConversation(String id) async {
    deleteCalls.add(id);
  }

  @override
  Future<List<ChatMessage>> getMessages(String conversationId) async => [];

  @override
  Stream<ChatStreamEvent> streamMessage(String id, String content) async* {
    yield const ChatStreamEvent('start', {});
    yield const ChatStreamEvent('content', {'delta': '收到'});
    yield ChatStreamEvent('title', {'conversation_id': id, 'title': '小模型生成标题'});
    yield const ChatStreamEvent('done', {});
  }
}

class _InterruptedToolApi extends _ConversationApi {
  @override
  Stream<ChatStreamEvent> streamMessage(String id, String content) async* {
    yield const ChatStreamEvent('start', {});
    yield const ChatStreamEvent('tool_start', {
      'id': 'tool-1',
      'name': 'parse_pdf_attachment',
    });
  }

  @override
  Future<List<ChatMessage>> getMessages(String conversationId) async => [];
}

class _LegacyConversationApi extends _ConversationApi {
  final Map<String, String> renamed = {};

  @override
  Stream<ChatStreamEvent> streamMessage(String id, String content) async* {
    yield const ChatStreamEvent('start', {});
    yield const ChatStreamEvent('content', {'delta': '收到'});
    yield const ChatStreamEvent('done', {});
  }

  @override
  Future<ChatConversation> getConversation(String id) {
    throw ApiException(405, '旧后端尚未提供此接口');
  }

  @override
  Future<void> renameConversation(String id, String title) async {
    renamed[id] = title;
  }
}

class _LearningOverviewApi extends _ConversationApi {
  @override
  Future<List<LearningCourseSummary>> getLearningCourses() async => const [
    LearningCourseSummary(
      name: '数据结构',
      totalPoints: 24,
      evaluatedPoints: 10,
      weakPoints: 2,
      reviewPoints: 1,
      averageMastery: 68,
    ),
  ];

  @override
  Future<MasteryReport> getMasteryReport({String course = ''}) async =>
      const MasteryReport(
        totalPoints: 10,
        averageMastery: 68,
        weakPoints: [MasteryPoint(name: '图的遍历', masteryLevel: 42)],
        strongPoints: [],
        stalePoints: [],
      );
}

void main() {
  test('新对话在首次发送前不会写入后端', () async {
    final api = _ConversationApi()
      ..sessionId = 'session'
      ..userId = 'user'
      ..username = 'tester';
    final state = AppState(api: api);
    addTearDown(state.dispose);

    await state.newConversation();
    expect(api.createCalls, 0);

    await state.send('第一个问题');
    expect(api.createCalls, 1);
    expect(state.messages, isNotEmpty);
    expect(state.activeConversation?.title, '小模型生成标题');

    await state.newConversation();
    expect(api.createCalls, 1);
    expect(state.messages, isEmpty);

    await state.newConversation();
    expect(api.createCalls, 1);
    expect(state.activeId, isNull);

    await state.send('第二个问题');
    expect(api.createCalls, 2);
    expect(state.activeId, 'conversation-2');
    expect(api.deleteCalls, isEmpty);
  });

  test('切走服务端已有的空白新对话时会自动删除', () async {
    final api = _ConversationApi()
      ..sessionId = 'session'
      ..userId = 'user'
      ..username = 'tester';
    final state = AppState(api: api);
    addTearDown(state.dispose);

    final empty = await api.createConversation();
    final existing = await api.createConversation();
    existing.title = '已有对话';
    state.conversations.addAll([empty, existing]);

    await state.setActive(empty.id);
    await state.setActive(existing.id);

    expect(api.deleteCalls, [empty.id]);
    expect(state.conversations.map((item) => item.id), [existing.id]);
    expect(state.activeId, existing.id);
  });

  test('工具调用期间连接中断会停止进度状态', () async {
    final api = _InterruptedToolApi()
      ..sessionId = 'session'
      ..userId = 'user'
      ..username = 'tester';
    final state = AppState(api: api);
    addTearDown(state.dispose);

    await state.send('解析附件');

    final tool = state.messages.singleWhere((message) => message.isTool);
    expect(tool.toolRunning, isFalse);
    expect(tool.text, '工具调用未完成：连接已中断');
  });

  test('旧后端没有标题事件时使用首问短标题兜底', () async {
    final api = _LegacyConversationApi()
      ..sessionId = 'session'
      ..userId = 'user'
      ..username = 'tester';
    final state = AppState(api: api);
    addTearDown(state.dispose);

    await state.send('请解释虚拟内存和页面置换算法之间的关系');

    expect(state.activeConversation?.title, '请解释虚拟内存和页面置换算法之间的关系');
    expect(api.renamed[state.activeId], state.activeConversation?.title);
  });

  test('学习概览从后端课程与掌握度接口加载', () async {
    final api = _LearningOverviewApi()
      ..sessionId = 'session'
      ..userId = 'user'
      ..username = 'tester';
    final state = AppState(api: api);
    addTearDown(state.dispose);

    await state.loadLearningOverview();

    expect(state.learningOverviewError, isNull);
    expect(state.learningCourses.single.name, '数据结构');
    expect(state.masteryReport?.averageMastery, 68);
    expect(state.masteryReport?.weakPoints.single.name, '图的遍历');
  });
}
