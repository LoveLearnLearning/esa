import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/theme/esa_theme.dart';
import 'package:frontend/widgets/assistant_message.dart';
import 'package:frontend/widgets/message_bubble.dart';
import 'package:frontend/widgets/tool_call_card.dart';

void main() {
  Widget app(Widget child) => MaterialApp(
    theme: esaTheme(brightness: Brightness.dark),
    home: Scaffold(body: child),
  );

  String? copiedText;

  setUp(() {
    copiedText = null;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (call) async {
          if (call.method == 'Clipboard.setData') {
            copiedText =
                (call.arguments as Map<Object?, Object?>)['text'] as String?;
          }
          return null;
        });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null);
  });

  testWidgets('assistant reasoning and code are selectable', (tester) async {
    final message = ChatMessage(
      id: 'assistant-1',
      role: MessageRole.assistant,
      reasoning: '先分析题目的约束条件',
      text: '''```dart
final answer = 42;
```''',
    );

    await tester.pumpWidget(
      app(AssistantMessage(message: message, onRegenerate: () {})),
    );

    expect(find.byType(SelectionArea), findsOneWidget);
    expect(find.byType(SelectableText), findsNothing);

    await tester.tap(find.text('思考过程'));
    await tester.pumpAndSettle();

    expect(find.byType(SelectionArea), findsNWidgets(2));
    expect(find.byType(SelectableText), findsNothing);
    expect(find.text('final answer = 42;', findRichText: true), findsOneWidget);
  });

  testWidgets('assistant copy action writes the complete response', (
    tester,
  ) async {
    final message = ChatMessage(
      id: 'assistant-copy',
      role: MessageRole.assistant,
      text: '第一行\n\n第二行',
    );

    await tester.pumpWidget(
      app(AssistantMessage(message: message, onRegenerate: () {})),
    );
    await tester.tap(find.byTooltip('复制'));
    await tester.pump();

    expect(copiedText, '第一行\n\n第二行');
  });

  testWidgets('assistant never renders raw tool call protocol', (tester) async {
    final message = ChatMessage(
      id: 'assistant-tool-markup',
      role: MessageRole.assistant,
      text: '''工具前的说明
<tool_call>
<function=calculator>
<parameter=expression>1 + 2</parameter>
</function>
</tool_call>
工具后的最终回答''',
    );

    await tester.pumpWidget(
      app(AssistantMessage(message: message, onRegenerate: () {})),
    );

    expect(find.textContaining('工具前的说明'), findsOneWidget);
    expect(find.textContaining('工具后的最终回答'), findsOneWidget);
    expect(find.textContaining('<tool_call>'), findsNothing);
    expect(find.textContaining('<function='), findsNothing);
    expect(find.textContaining('<parameter='), findsNothing);
  });

  testWidgets('assistant repaints while the same message streams', (
    tester,
  ) async {
    final message = ChatMessage.typingPlaceholder();
    var contentChanges = 0;
    await tester.pumpWidget(
      app(
        AssistantMessage(
          message: message,
          onRegenerate: () {},
          onContentChanged: () => contentChanges++,
        ),
      ),
    );

    message.text = '实时';
    message.notifyListeners();
    await tester.pump();
    expect(find.text('实时'), findsOneWidget);

    message.text += '生成';
    message.notifyListeners();
    await tester.pump();
    expect(find.text('实时生成'), findsOneWidget);
    expect(contentChanges, 2);

    message.typing = false;
    message.notifyListeners();
    await tester.pump();
  });

  testWidgets('user message is selectable and has a working copy action', (
    tester,
  ) async {
    await tester.pumpWidget(app(const UserBubble(text: '用户的两行\n消息')));

    expect(find.byType(SelectionArea), findsOneWidget);
    await tester.tap(find.byTooltip('复制'));
    await tester.pump();

    expect(copiedText, '用户的两行\n消息');
    expect(find.byTooltip('已复制'), findsOneWidget);
  });

  testWidgets('Ctrl+C copies the selected part of a user message', (
    tester,
  ) async {
    await tester.pumpWidget(app(const UserBubble(text: '只复制选中的文字')));

    final selectionArea = tester.widget<SelectionArea>(
      find.byType(SelectionArea),
    );
    selectionArea.onSelectionChanged!(
      const SelectedContent(plainText: '选中的文字'),
    );
    Actions.invoke(
      tester.element(find.text('只复制选中的文字')),
      CopySelectionTextIntent.copy,
    );
    await tester.pump();

    expect(copiedText, '选中的文字');
  });

  testWidgets('tool output is selectable', (tester) async {
    await tester.pumpWidget(
      app(const ToolCallCard(name: 'calculator', output: '{"value": 42}')),
    );

    expect(find.byType(SelectableText), findsOneWidget);
    expect(find.text('{"value": 42}'), findsOneWidget);
  });
}
