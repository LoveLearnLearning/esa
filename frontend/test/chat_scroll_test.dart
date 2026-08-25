import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/pages/chat_page.dart';
import 'package:frontend/state/app_state.dart';
import 'package:frontend/theme/esa_theme.dart';

class _FakeApiClient extends ApiClient {
  _FakeApiClient(this.conversationData, this.messageData)
    : super(baseUrl: 'http://test.invalid');

  final List<ChatConversation> conversationData;
  final Map<String, List<ChatMessage>> messageData;

  @override
  Future<List<ChatConversation>> listConversations() async =>
      List.of(conversationData);

  @override
  Future<List<ChatMessage>> getMessages(String id) async =>
      List.of(messageData[id] ?? const []);

  @override
  Stream<ChatStreamEvent> streamMessage(
    String id,
    String content, {
    String? personalKnowledgeBaseId,
  }) async* {
    yield const ChatStreamEvent('start', {});
    yield const ChatStreamEvent('content', {'delta': '收到'});
    yield const ChatStreamEvent('done', {});
  }
}

void main() {
  const listKey = ValueKey('chat-message-list');

  List<ChatMessage> longConversation(String prefix) => List.generate(
    24,
    (index) => ChatMessage(
      id: '$prefix-$index',
      role: index.isEven ? MessageRole.user : MessageRole.assistant,
      text: '$prefix 第 $index 条消息\n这是用于验证滚动位置的第二行。',
    ),
  );

  Future<({AppState state, _FakeApiClient api})> createState() async {
    final conversations = [
      ChatConversation(id: 'first', title: '第一个对话', updatedAt: DateTime(2026)),
      ChatConversation(id: 'second', title: '第二个对话', updatedAt: DateTime(2026)),
    ];
    final api =
        _FakeApiClient(conversations, {
            'first': longConversation('第一'),
            'second': longConversation('第二'),
          })
          ..sessionId = 'session'
          ..userId = 'user'
          ..username = 'tester';
    final state = AppState(api: api);
    await state.loadConversations();
    await state.setActive('first');
    return (state: state, api: api);
  }

  Widget app(AppState state) => AppScope(
    state: state,
    child: MaterialApp(
      theme: esaTheme(brightness: Brightness.dark),
      home: const ChatPage(),
    ),
  );

  ScrollPosition position(WidgetTester tester) {
    final list = tester.widget<ListView>(find.byKey(listKey));
    return list.controller!.position;
  }

  bool isAtBottom(ScrollPosition value) =>
      (value.maxScrollExtent - value.pixels).abs() <= 1;

  testWidgets('opens a loaded conversation at the bottom', (tester) async {
    final fixture = await createState();
    addTearDown(fixture.state.dispose);

    await tester.pumpWidget(app(fixture.state));
    await tester.pumpAndSettle();

    expect(position(tester).maxScrollExtent, greaterThan(0));
    final finalPosition = position(tester);
    expect(
      isAtBottom(finalPosition),
      isTrue,
      reason:
          'pixels=${finalPosition.pixels}, max=${finalPosition.maxScrollExtent}',
    );
  });

  testWidgets('sending while reading earlier messages resumes bottom follow', (
    tester,
  ) async {
    final fixture = await createState();
    addTearDown(fixture.state.dispose);
    await tester.pumpWidget(app(fixture.state));
    await tester.pump();

    await tester.drag(find.byKey(listKey), const Offset(0, 450));
    await tester.pumpAndSettle();
    expect(isAtBottom(position(tester)), isFalse);

    await tester.enterText(find.byType(TextField), '新问题');
    await tester.pump();
    await tester.tap(find.bySemanticsLabel('发送'));
    await tester.pumpAndSettle();

    expect(find.text('新问题'), findsOneWidget);
    final finalPosition = position(tester);
    expect(
      isAtBottom(finalPosition),
      isTrue,
      reason:
          'pixels=${finalPosition.pixels}, max=${finalPosition.maxScrollExtent}',
    );
  });

  testWidgets('switching history conversations resets to the bottom', (
    tester,
  ) async {
    final fixture = await createState();
    addTearDown(fixture.state.dispose);
    await tester.pumpWidget(app(fixture.state));
    await tester.pump();

    await tester.drag(find.byKey(listKey), const Offset(0, 450));
    await tester.pumpAndSettle();
    expect(isAtBottom(position(tester)), isFalse);

    await fixture.state.setActive('second');
    await tester.pumpAndSettle();

    expect(find.textContaining('第二 第 23 条消息'), findsOneWidget);
    expect(isAtBottom(position(tester)), isTrue);
  });

  testWidgets('mouse wheel disables stream following while reading upward', (
    tester,
  ) async {
    final fixture = await createState();
    addTearDown(fixture.state.dispose);
    await tester.pumpWidget(app(fixture.state));
    await tester.pumpAndSettle();

    await tester.sendEventToBinding(
      PointerScrollEvent(
        position: tester.getCenter(find.byKey(listKey)),
        scrollDelta: const Offset(0, -450),
      ),
    );
    await tester.pumpAndSettle();
    final readingPosition = position(tester).pixels;
    expect(isAtBottom(position(tester)), isFalse);

    final streamingMessage = fixture.api.messageData['first']!.last;
    streamingMessage.text += '\n新到达的流式内容';
    streamingMessage.notifyListeners();
    await tester.pumpAndSettle();

    expect(position(tester).pixels, closeTo(readingPosition, 1));
    expect(isAtBottom(position(tester)), isFalse);
  });

  testWidgets(
    'touching messages during generation dismisses keyboard and permits drag',
    (tester) async {
      final fixture = await createState();
      addTearDown(fixture.state.dispose);
      await tester.pumpWidget(app(fixture.state));
      await tester.pumpAndSettle();

      final streamingMessage = fixture.api.messageData['first']!.last;
      streamingMessage.typing = true;
      streamingMessage.notifyListeners();
      await tester.pump(const Duration(milliseconds: 130));

      final field = tester.widget<TextField>(find.byType(TextField));
      await tester.tap(find.byType(TextField));
      await tester.pump();
      expect(field.focusNode!.hasFocus, isTrue);

      final bottomPosition = position(tester).pixels;
      final gesture = await tester.startGesture(
        tester.getCenter(find.byKey(listKey)),
      );
      await tester.pump();
      expect(field.focusNode!.hasFocus, isFalse);

      // 真机首先产生很小的移动。旧实现会在 extentAfter <= 24 时误恢复
      // 自动追底，导致后续拖动被流式更新重新拉回底部。
      await gesture.moveBy(const Offset(0, 10));
      await tester.pump();

      streamingMessage.text += '\n按下后到达的流式内容';
      streamingMessage.notifyListeners();
      await tester.pump(const Duration(milliseconds: 150));
      expect(find.textContaining('按下后到达的流式内容'), findsNothing);

      await gesture.moveBy(const Offset(0, 310));
      await tester.pump();
      await gesture.up();
      await tester.pump(const Duration(milliseconds: 30));

      expect(position(tester).pixels, lessThan(bottomPosition - 50));
      expect(isAtBottom(position(tester)), isFalse);

      streamingMessage.typing = false;
      streamingMessage.notifyListeners();
      await tester.pump(const Duration(milliseconds: 130));
    },
  );
}
