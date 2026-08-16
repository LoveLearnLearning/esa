import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/state/app_state.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _GroupApi extends ApiClient {
  _GroupApi() : super(baseUrl: 'http://test.invalid');

  final List<ChatGroup> groups = [];
  final List<ChatConversation> conversations = [];
  String? lastCreatedConversationGroupId;
  String? lastCreatedConversationResearchProjectId;

  @override
  Future<List<ChatGroup>> listGroups() async => List.of(groups);

  @override
  Future<ChatGroup> createGroup({
    required String name,
    String description = '',
    String customInstruction = '',
    String? style,
    String? tone,
  }) async {
    final group = ChatGroup(
      id: 'group-${groups.length + 1}',
      userId: 'user-1',
      name: name,
      description: description,
      customInstruction: customInstruction,
      style: style,
      tone: tone,
      conversationCount: 0,
      createdAt: DateTime(2026),
      updatedAt: DateTime(2026),
    );
    groups.insert(0, group);
    return group;
  }

  @override
  Future<void> deleteGroup(String groupId) async {
    groups.removeWhere((group) => group.id == groupId);
    for (final conversation in conversations) {
      if (conversation.groupId == groupId) conversation.groupId = null;
    }
  }

  @override
  Future<void> moveConversation(String id, String? groupId) async {
    final index = conversations.indexWhere(
      (conversation) => conversation.id == id,
    );
    if (index >= 0) conversations[index].groupId = groupId;
  }

  @override
  Future<List<ChatConversation>> listConversations() async =>
      List.of(conversations);

  @override
  Future<ChatConversation> createConversation({String? groupId}) async {
    lastCreatedConversationGroupId = groupId;
    final conversation = ChatConversation(
      id: 'conversation-${conversations.length + 1}',
      title: '新对话',
      updatedAt: DateTime(2026),
      groupId: groupId,
    );
    conversations.insert(0, conversation);
    return conversation;
  }

  @override
  Future<ChatConversation> createWorkspaceConversation(
    WorkspaceType workspace, {
    String? researchProjectId,
    String? classId,
    String? assignmentId,
    String? groupId,
  }) async {
    lastCreatedConversationGroupId = groupId;
    lastCreatedConversationResearchProjectId = researchProjectId;
    final conversation = ChatConversation(
      id: 'conversation-${conversations.length + 1}',
      title: '新对话',
      updatedAt: DateTime(2026),
      workspaceType: workspace,
      researchProjectId: researchProjectId,
      groupId: groupId,
    );
    conversations.insert(0, conversation);
    return conversation;
  }

  @override
  Future<void> renameConversation(String id, String title) async {}

  @override
  Stream<ChatStreamEvent> streamMessage(String id, String content) async* {
    yield const ChatStreamEvent('start', {});
    yield const ChatStreamEvent('content', {'delta': '收到'});
    yield const ChatStreamEvent('done', {});
  }
}

ChatConversation _conversation(String id, String? groupId) => ChatConversation(
  id: id,
  title: id,
  updatedAt: DateTime(2026),
  groupId: groupId,
);

ChatGroup _group(String id, int count) => ChatGroup(
  id: id,
  userId: 'user-1',
  name: id,
  description: '',
  customInstruction: '',
  conversationCount: count,
  createdAt: DateTime(2026),
  updatedAt: DateTime(2026),
);

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('loads groups and exposes grouped/ungrouped conversation buckets', () async {
    final api = _GroupApi()
      ..groups.addAll([_group('group-1', 1), _group('group-2', 0)])
      ..conversations.addAll([
        _conversation('conversation-1', 'group-1'),
        _conversation('conversation-2', null),
      ]);
    final state = AppState(api: api);
    addTearDown(state.dispose);

    await state.loadGroups();
    await state.loadConversations();

    expect(state.groups, hasLength(2));
    expect(state.groupedConversations, hasLength(1));
    expect(state.ungroupedConversations, hasLength(1));
    expect(state.conversationsInGroup('group-1').single.id, 'conversation-1');
  });

  test('moving a conversation updates membership and local group counts', () async {
    final api = _GroupApi()
      ..groups.addAll([_group('group-1', 1), _group('group-2', 0)])
      ..conversations.addAll([
        _conversation('conversation-1', 'group-1'),
        _conversation('conversation-2', null),
      ]);
    final state = AppState(api: api);
    addTearDown(state.dispose);
    await state.loadGroups();
    await state.loadConversations();

    await state.moveConversationToGroup('conversation-2', 'group-1');

    expect(state.conversationsInGroup('group-1'), hasLength(2));
    expect(state.ungroupedConversations, hasLength(0));
    expect(
      state.groups.firstWhere((group) => group.id == 'group-1').conversationCount,
      2,
    );

    await state.moveConversationToGroup('conversation-2', null);

    expect(state.ungroupedConversations, hasLength(1));
    expect(
      state.groups.firstWhere((group) => group.id == 'group-1').conversationCount,
      1,
    );
  });

  test('deleting a group moves its conversations back to ungrouped', () async {
    final api = _GroupApi()
      ..groups.addAll([_group('group-1', 1), _group('group-2', 0)])
      ..conversations.addAll([
        _conversation('conversation-1', 'group-1'),
        _conversation('conversation-2', null),
      ]);
    final state = AppState(api: api);
    addTearDown(state.dispose);
    await state.loadGroups();
    await state.loadConversations();

    await state.deleteGroup('group-1');

    expect(state.groups.map((group) => group.id), ['group-2']);
    expect(state.conversationsInGroup('group-1'), isEmpty);
    expect(state.ungroupedConversations, hasLength(2));
  });

  test('group conversations are created on first send inside the active group', () async {
    final api = _GroupApi();
    final state = AppState(api: api)
      ..activeGroupId = 'group-1';
    addTearDown(state.dispose);

    await state.newConversation();
    expect(api.lastCreatedConversationGroupId, isNull);

    await state.send('分组中的第一个问题');

    expect(api.lastCreatedConversationGroupId, 'group-1');
    expect(state.activeConversation?.groupId, 'group-1');
  });

  test('new conversation can target a specific group', () async {
    final api = _GroupApi();
    final state = AppState(api: api)..activeGroupId = 'group-1';
    addTearDown(state.dispose);

    await state.newConversationInGroup('group-2');
    await state.send('分组中的第一个问题');

    expect(state.activeGroupId, 'group-2');
    expect(api.lastCreatedConversationGroupId, 'group-2');
    expect(state.activeConversation?.groupId, 'group-2');
  });

  test('toggling a group pin moves it to the top', () async {
    final api = _GroupApi()
      ..groups.addAll([_group('group-1', 1), _group('group-2', 0)]);
    final state = AppState(api: api);
    addTearDown(state.dispose);
    await state.loadGroups();

    expect(state.groups.map((group) => group.id), ['group-1', 'group-2']);

    state.toggleGroupPin('group-2');

    expect(state.isGroupPinned('group-2'), isTrue);
    expect(state.groups.map((group) => group.id), ['group-2', 'group-1']);

    state.toggleGroupPin('group-2');

    expect(state.isGroupPinned('group-2'), isFalse);
    expect(state.groups.map((group) => group.id), ['group-2', 'group-1']);
  });

  test('creating a group inside a project binds it to that project', () async {
    final api = _GroupApi();
    final state = AppState(api: api);
    addTearDown(state.dispose);

    final group = await state.createGroup(
      name: '文献检索',
      projectId: 'project-1',
    );

    expect(state.groupProjectId(group.id), 'project-1');
    expect(state.groupsForProject('project-1').single.id, group.id);
    expect(state.groupsForProject('project-2'), isEmpty);
  });

  test('research groups are scoped to existing projects', () async {
    final api = _GroupApi()
      ..groups.addAll([_group('group-1', 1), _group('group-2', 0)])
      ..conversations.addAll([
        ChatConversation(
          id: 'conversation-project-1',
          title: '项目对话',
          updatedAt: DateTime(2026),
          workspaceType: WorkspaceType.research,
          researchProjectId: 'project-1',
          groupId: 'group-1',
        ),
      ]);
    final state = AppState(api: api);
    addTearDown(state.dispose);
    await state.loadGroups();
    await state.loadConversations();

    expect(state.groupsForProject('project-1').map((group) => group.id), [
      'group-1',
    ]);
    expect(state.groupsForProject('project-2'), isEmpty);
    expect(
      state.conversationsInGroupForProject('group-1', 'project-1'),
      hasLength(1),
    );
    expect(state.ungroupedConversationsInProject('project-1'), isEmpty);
  });

  test('research conversation in a group keeps the project binding', () async {
    final api = _GroupApi();
    final state = AppState(api: api);
    addTearDown(state.dispose);
    await state.createGroup(name: '文献检索', projectId: 'project-1');
    state.activeWorkspace = WorkspaceType.research;

    await state.newConversationInGroup(
      'group-1',
      researchProjectId: 'project-1',
    );
    await state.send('检索一篇论文');

    expect(api.lastCreatedConversationResearchProjectId, 'project-1');
    expect(api.lastCreatedConversationGroupId, 'group-1');
    expect(state.activeConversation?.researchProjectId, 'project-1');
    expect(state.activeConversation?.groupId, 'group-1');
  });
}
