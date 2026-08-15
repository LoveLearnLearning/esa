import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/state/app_state.dart';

class _GroupApi extends ApiClient {
  _GroupApi() : super(baseUrl: 'http://test.invalid');

  final List<ChatGroup> groups = [];
  final List<ChatConversation> conversations = [];
  String? lastCreatedConversationGroupId;

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
}
