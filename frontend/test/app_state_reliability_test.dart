import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/state/app_state.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _ReliabilityApi extends ApiClient {
  _ReliabilityApi() : super(baseUrl: 'http://test.invalid');

  final Map<String, Future<List<ChatMessage>> Function()> messageLoaders = {};
  final Map<String, Future<ChatConversation> Function()> conversationLoaders =
      {};
  final Map<WorkspaceType, Future<List<ChatConversation>> Function()>
  workspaceLoaders = {};
  Future<List<ResearchProject>> Function()? researchProjectsLoader;
  Future<List<TeachingAssignment>> Function()? assignmentsLoader;
  Future<void> Function()? logoutHandler;
  Future<void> Function(String)? deleteHandler;
  Future<ScheduleSnapshot> Function()? scheduleLoader;
  final Map<String, Stream<ChatStreamEvent>> streams = {};

  @override
  Future<void> logout() => logoutHandler?.call() ?? Future.value();

  @override
  Future<void> deleteConversation(String id) =>
      deleteHandler?.call(id) ?? Future.value();

  @override
  Future<void> renameConversation(String id, String title) async {}

  @override
  Future<ChatConversation> getConversation(String id) =>
      conversationLoaders[id]?.call() ?? super.getConversation(id);

  @override
  Future<List<ChatMessage>> sendMessage(
    String id,
    String content, {
    String? personalKnowledgeBaseId,
  }) async => [ChatMessage.user(content)];

  @override
  Future<ScheduleSnapshot> getSchedule() async => scheduleLoader == null
      ? ScheduleSnapshot.fromJson({})
      : scheduleLoader!();

  @override
  Stream<ChatStreamEvent> streamMessage(
    String id,
    String content, {
    String? personalKnowledgeBaseId,
  }) => streams[id] ?? const Stream.empty();

  @override
  Stream<ChatStreamEvent> streamRevisedMessage(
    String id,
    String content,
    int messageId,
    List<String> attachmentIds, {
    Set<KnowledgeSource> knowledgeSources = const {
      KnowledgeSource.personal,
      KnowledgeSource.public,
    },
    String? personalKnowledgeBaseId,
  }) => streams[id] ?? const Stream.empty();

  @override
  Future<List<ChatMessage>> getMessages(String id) =>
      messageLoaders[id]?.call() ?? Future.value([]);

  @override
  Future<List<ChatConversation>> listConversations() =>
      workspaceLoaders[WorkspaceType.learning]?.call() ??
      Future.value(const []);

  @override
  Future<List<ChatConversation>> listWorkspaceConversations(
    WorkspaceType workspace,
  ) => workspaceLoaders[workspace]?.call() ?? Future.value(const []);

  @override
  Future<List<ResearchProject>> listResearchProjects() =>
      researchProjectsLoader?.call() ?? Future.value(const []);

  @override
  Future<List<TeachingAssignment>> listStudentAssignments() =>
      assignmentsLoader?.call() ?? Future.value(const []);
}

class _NotificationTrackingState extends AppState {
  _NotificationTrackingState({required super.api});

  int notifications = 0;

  @override
  void notifyListeners() {
    notifications++;
    super.notifyListeners();
  }
}

ChatConversation _conversation(String id) =>
    ChatConversation(id: id, title: id, updatedAt: DateTime(2026));

const _workspaces = [
  WorkspaceDescriptor(
    type: WorkspaceType.learning,
    name: '学习空间',
    description: '',
    capabilities: ['chat'],
  ),
  WorkspaceDescriptor(
    type: WorkspaceType.teaching,
    name: '教学空间',
    description: '',
    capabilities: ['chat'],
  ),
  WorkspaceDescriptor(
    type: WorkspaceType.research,
    name: '科研空间',
    description: '',
    capabilities: ['chat', 'research_projects'],
  ),
];

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  for (final newerCompletesFirst in [true, false]) {
    test(
      'same-chat refresh keeps the latest request ($newerCompletesFirst)',
      () async {
        final older = Completer<List<ChatMessage>>();
        final newer = Completer<List<ChatMessage>>();
        final api = _ReliabilityApi()..sessionId = 'session';
        final state = AppState(api: api)..activeId = 'history';
        addTearDown(state.dispose);
        api.messageLoaders['history'] = () => older.future;
        final oldLoad = state.reloadActiveMessages();
        api.messageLoaders['history'] = () => newer.future;
        final newLoad = state.reloadActiveMessages();

        if (!newerCompletesFirst) {
          older.completeError(ApiException(401, '旧请求失败'));
          await oldLoad;
          expect(state.loadingMessages, isTrue);
        }
        newer.complete([
          ChatMessage(id: 'latest', role: MessageRole.user, text: '最新记录'),
        ]);
        await newLoad;
        if (newerCompletesFirst) {
          older.completeError(ApiException(401, '旧请求失败'));
          await oldLoad;
        }

        expect(api.sessionId, 'session');
        expect(state.messages.single.text, '最新记录');
        expect(state.loadingMessages, isFalse);
        expect(state.activeMessagesError, isNull);
      },
    );
  }

  test('delayed draft deletion cannot steal a newer selection', () async {
    final deletion = Completer<void>();
    final api = _ReliabilityApi()..deleteHandler = (_) => deletion.future;
    final state = AppState(api: api)
      ..conversations.add(
        ChatConversation(id: 'draft', title: '新对话', updatedAt: DateTime(2026)),
      );
    addTearDown(state.dispose);
    await state.setActive('draft');

    final firstSelection = state.setActive('first');
    await state.setActive('latest');
    deletion.complete();
    await firstSelection;

    expect(state.activeId, 'latest');
  });

  test(
    'schedule refresh failure retains the last successful snapshot',
    () async {
      final snapshot = ScheduleSnapshot.fromJson({
        'active_table_id': 'saved-table',
        'courses': [
          {'id': 'course-1', 'name': '已有课程'},
        ],
      });
      final api = _ReliabilityApi()..scheduleLoader = () async => snapshot;
      final state = AppState(api: api);
      addTearDown(state.dispose);
      await state.loadSchedule();
      api.scheduleLoader = () async => throw ApiException(503, '课表服务暂时不可用');

      await state.loadSchedule(force: true);

      expect(state.scheduleCourses.single.name, '已有课程');
      expect(state.activeScheduleTableId, 'saved-table');
      expect(state.scheduleLoaded, isTrue);
      expect(state.scheduleError, '课表服务暂时不可用');
    },
  );

  for (final fail in [true, false]) {
    test(
      'old account list responses are ignored after logout ($fail)',
      () async {
        final schedule = Completer<ScheduleSnapshot>();
        final assignments = Completer<List<TeachingAssignment>>();
        final api = _ReliabilityApi()
          ..sessionId = 'old'
          ..userId = 'old-user';
        api.scheduleLoader = () => schedule.future;
        api.assignmentsLoader = () => assignments.future;
        final state = AppState(api: api);
        addTearDown(state.dispose);
        final loading = Future.wait([
          state.loadSchedule(),
          state.loadStudentAssignments(),
        ]);
        await state.logout();
        api.sessionId = 'new';
        api.userId = 'new-user';

        if (fail) {
          schedule.completeError(ApiException(401, '已过期'));
          assignments.completeError(ApiException(401, '已过期'));
        } else {
          schedule.complete(
            ScheduleSnapshot.fromJson({'active_table_id': 'old-table'}),
          );
          assignments.complete([
            TeachingAssignment.fromJson({'assignment_id': 'old-assignment'}),
          ]);
        }
        await loading;

        expect(api.sessionId, 'new');
        expect(state.activeScheduleTableId, isEmpty);
        expect(state.scheduleLoaded, isFalse);
        expect(state.studentAssignments, isEmpty);
        expect(state.scheduleError, isNull);
        expect(state.studentAssignmentsError, isNull);
        final preferences = await SharedPreferences.getInstance();
        expect(
          preferences.getKeys().where((key) => key.contains('new-user')),
          isEmpty,
        );
      },
    );
  }

  test('disposal invalidates pending history and schedule loads', () async {
    final messages = Completer<List<ChatMessage>>();
    final schedule = Completer<ScheduleSnapshot>();
    final api = _ReliabilityApi()..scheduleLoader = () => schedule.future;
    api.messageLoaders['history'] = () => messages.future;
    final state = AppState(api: api);
    final loading = Future.wait([
      state.setActive('history'),
      state.loadSchedule(),
    ]);
    await Future<void>.delayed(Duration.zero);
    state.dispose();
    messages.complete([
      ChatMessage(id: 'late', role: MessageRole.user, text: '过期内容'),
    ]);
    schedule.complete(ScheduleSnapshot.fromJson({}));
    await loading;

    expect(state.messages, isEmpty);
    expect(state.scheduleLoaded, isFalse);
  });

  for (final revise in [true, false]) {
    test(
      'canceling an old stream cannot stop a new session ($revise)',
      () async {
        final cancellation = Completer<void>();
        final oldEvents = StreamController<ChatStreamEvent>(
          onCancel: () => cancellation.future,
        );
        final newEvents = StreamController<ChatStreamEvent>();
        addTearDown(() {
          if (!cancellation.isCompleted) cancellation.complete();
          unawaited(oldEvents.close());
          unawaited(newEvents.close());
        });
        final api = _ReliabilityApi()..sessionId = 'old';
        api.streams['old-chat'] = oldEvents.stream;
        api.streams['new-chat'] = newEvents.stream;
        api.messageLoaders['old-chat'] = () async => [
          ChatMessage(id: '1', role: MessageRole.user, text: '原问题'),
        ];
        final state = AppState(api: api);
        addTearDown(state.dispose);
        await state.setActive('old-chat');
        final oldSend = revise
            ? state.reviseUserMessage(state.messages.first, '修改的问题')
            : state.send('旧问题');
        expect(oldEvents.hasListener, isTrue);
        oldEvents.add(const ChatStreamEvent('content', {'delta': '旧回答'}));
        await Future<void>.delayed(Duration.zero);
        await state.logout();
        api.sessionId = 'new';
        await state.setActive('new-chat');
        final newSend = state.send('新问题');

        cancellation.complete();
        await oldSend;

        expect(state.busy, isTrue);
        expect(newEvents.hasListener, isTrue);
        expect(state.messages.first.text, '新问题');
        expect(
          state.messages.any((message) => message.text.contains('旧回答')),
          isFalse,
        );
        await state.stopGeneration();
        await newSend;
        expect(state.busy, isFalse);
        expect(newEvents.hasListener, isFalse);
      },
    );
  }

  test(
    'disposal during fallback title loading stops send notifications',
    () async {
      final titleResponse = Completer<ChatConversation>();
      final titleRequested = Completer<void>();
      final api = _ReliabilityApi()..sessionId = 'session';
      api.conversationLoaders['history'] = () {
        titleRequested.complete();
        return titleResponse.future;
      };
      final state = _NotificationTrackingState(api: api)
        ..activeId = 'history'
        ..streamOn = false
        ..conversations.add(
          ChatConversation(
            id: 'history',
            title: '新对话',
            updatedAt: DateTime(2026),
          ),
        );

      final sending = state.send('question');
      await titleRequested.future;
      state.dispose();
      final notifications = state.notifications;
      titleResponse.complete(_conversation('history'));
      await sending;
      expect(state.notifications, notifications);
    },
  );

  for (final failureAsEvent in [true, false]) {
    test('stream failure cancels its source ($failureAsEvent)', () async {
      var cancelled = false;
      final events = StreamController<ChatStreamEvent>(
        onCancel: () => cancelled = true,
      );
      addTearDown(() => unawaited(events.close()));
      final api = _ReliabilityApi()..sessionId = 'session';
      api.streams['history'] = events.stream;
      final state = AppState(api: api)..activeId = 'history';
      addTearDown(state.dispose);

      final sending = state.send('question');
      if (failureAsEvent) {
        events.add(const ChatStreamEvent('error', {'detail': '生成回复失败'}));
      } else {
        events.addError(ApiException(500, '生成回复失败'));
      }
      await sending;

      expect(cancelled, isTrue);
      expect(state.busy, isFalse);
      expect(state.messages.last.text, contains('生成回复失败'));
    });
  }

  test('logout clears local state before remote logout completes', () async {
    final response = Completer<void>();
    final api = _ReliabilityApi()
      ..sessionId = 'old-session'
      ..logoutHandler = () => response.future;
    final state = AppState(api: api)..conversations.add(_conversation('old'));
    addTearDown(state.dispose);

    final logout = state.logout();
    final locallyLoggedOut = !state.isLoggedIn && state.conversations.isEmpty;
    response.complete();
    await logout;

    expect(locallyLoggedOut, isTrue);
  });

  test(
    'message load failure preserves cached messages and exposes retry error',
    () async {
      final api = _ReliabilityApi();
      final oldMessages = [
        ChatMessage(id: 'message-1', role: MessageRole.user, text: '历史消息'),
      ];
      api.messageLoaders['conversation-1'] = () async => oldMessages;
      final state = AppState(api: api)
        ..conversations.add(_conversation('conversation-1'));
      addTearDown(state.dispose);

      await state.setActive('conversation-1');
      api.messageLoaders['conversation-1'] = () async {
        throw ApiException(503, '消息服务暂时不可用');
      };

      await state.reloadActiveMessages();

      expect(state.messages, same(oldMessages));
      expect(state.activeMessagesError, '消息服务暂时不可用');
    },
  );

  test(
    'older conversation request cannot overwrite the active conversation',
    () async {
      final api = _ReliabilityApi();
      final first = Completer<List<ChatMessage>>();
      final second = Completer<List<ChatMessage>>();
      api.messageLoaders['conversation-1'] = () => first.future;
      api.messageLoaders['conversation-2'] = () => second.future;
      final state = AppState(api: api)
        ..conversations.addAll([
          _conversation('conversation-1'),
          _conversation('conversation-2'),
        ]);
      addTearDown(state.dispose);

      final firstLoad = state.setActive('conversation-1');
      await Future<void>.delayed(Duration.zero);
      final secondLoad = state.setActive('conversation-2');
      second.complete([
        ChatMessage(
          id: 'message-2',
          role: MessageRole.assistant,
          text: '第二个对话',
        ),
      ]);
      await secondLoad;
      expect(state.loadingMessages, isFalse);
      first.complete([
        ChatMessage(
          id: 'message-1',
          role: MessageRole.assistant,
          text: '第一个对话',
        ),
      ]);
      await firstLoad;

      expect(state.activeId, 'conversation-2');
      expect(state.messages.single.text, '第二个对话');
    },
  );

  test(
    'reopening a failed history load retries instead of caching an empty chat',
    () async {
      final api = _ReliabilityApi();
      var attempts = 0;
      api.messageLoaders['history'] = () async {
        if (++attempts == 1) throw ApiException(503, '加载失败');
        return [ChatMessage(id: 'saved', role: MessageRole.user, text: '已保存')];
      };
      final state = AppState(api: api)
        ..conversations.add(_conversation('history'));
      addTearDown(state.dispose);

      await state.setActive('history');
      expect(state.activeMessagesError, '加载失败');
      await state.setActive('history');
      expect(attempts, 2);
      expect(state.messages.single.text, '已保存');
      expect(state.activeMessagesError, isNull);
    },
  );

  test(
    'a stale unauthorized message response cannot clear a newer session',
    () async {
      final api = _ReliabilityApi()..sessionId = 'old-session';
      final oldResponse = Completer<List<ChatMessage>>();
      api.messageLoaders['history'] = () => oldResponse.future;
      final state = AppState(api: api)
        ..conversations.add(_conversation('history'));
      addTearDown(state.dispose);
      final pending = state.setActive('history');
      await Future<void>.delayed(Duration.zero);
      api.messageLoaders['expired'] = () async => throw ApiException(401, '过期');
      await state.setActive('expired');
      expect(state.isLoggedIn, isFalse);

      api.sessionId = 'new-session';
      oldResponse.completeError(ApiException(401, '旧会话过期'));
      await pending;

      expect(api.sessionId, 'new-session');
      expect(state.messagesErrorFor('history'), isNull);
    },
  );

  test(
    'returning immediately to the current workspace cancels a pending switch',
    () async {
      final state = AppState(api: _ReliabilityApi());
      addTearDown(state.dispose);

      final researchSwitch = state.switchWorkspace(WorkspaceType.research);
      final learningSwitch = state.switchWorkspace(WorkspaceType.learning);
      await Future.wait([researchSwitch, learningSwitch]);

      expect(state.activeWorkspace, WorkspaceType.learning);
    },
  );

  test('rapid workspace switches keep the latest workspace response', () async {
    final api = _ReliabilityApi();
    final research = Completer<List<ChatConversation>>();
    final teaching = Completer<List<ChatConversation>>();
    api.workspaceLoaders[WorkspaceType.research] = () => research.future;
    api.workspaceLoaders[WorkspaceType.teaching] = () => teaching.future;
    final state = AppState(api: api)..availableWorkspaces = _workspaces;
    addTearDown(state.dispose);

    final researchSwitch = state.switchWorkspace(WorkspaceType.research);
    await Future<void>.delayed(Duration.zero);
    final teachingSwitch = state.switchWorkspace(WorkspaceType.teaching);
    teaching.complete([_conversation('teaching-conversation')]);
    await teachingSwitch;
    research.complete([_conversation('research-conversation')]);
    await researchSwitch;

    expect(state.activeWorkspace, WorkspaceType.teaching);
    expect(state.conversations.single.id, 'teaching-conversation');
  });

  test(
    'research project and assignment failures preserve existing data',
    () async {
      final api = _ReliabilityApi();
      final project = ResearchProject(
        id: 'project-1',
        name: '已有项目',
        description: '',
        status: 'active',
        updatedAt: DateTime(2026),
      );
      api.researchProjectsLoader = () async => [project];
      final state = AppState(api: api);
      addTearDown(state.dispose);

      await state.loadResearchProjects();
      api.researchProjectsLoader = () async {
        throw ApiException(503, '科研服务暂时不可用');
      };
      await state.loadResearchProjects(force: true);

      expect(state.researchProjects.single.id, 'project-1');
      expect(state.researchProjectsError, '科研服务暂时不可用');

      final assignment = TeachingAssignment.fromJson({
        'assignment_id': 'assignment-1',
        'title': '已有作业',
      });
      api.assignmentsLoader = () async => [assignment];
      await state.loadStudentAssignments();
      api.assignmentsLoader = () async {
        throw ApiException(503, '作业服务暂时不可用');
      };
      await state.loadStudentAssignments();

      expect(state.studentAssignments.single, same(assignment));
      expect(state.studentAssignmentsError, '作业服务暂时不可用');
    },
  );
}
