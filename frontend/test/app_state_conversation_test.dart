import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/state/app_state.dart';

class _ConversationApi extends ApiClient {
  _ConversationApi() : super(baseUrl: 'http://test.invalid');

  int createCalls = 0;

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
  Stream<ChatStreamEvent> streamMessage(String id, String content) async* {
    yield const ChatStreamEvent('start', {});
    yield const ChatStreamEvent('content', {'delta': '收到'});
    yield const ChatStreamEvent('done', {});
  }
}

void main() {
  test('空白新对话不会被重复创建', () async {
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

    await state.newConversation();
    expect(api.createCalls, 2);
    expect(state.messages, isEmpty);

    await state.newConversation();
    expect(api.createCalls, 2);
    expect(state.activeId, 'conversation-2');
  });
}
