import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/theme/esa_theme.dart';
import 'package:frontend/widgets/assistant_message.dart';
import 'package:frontend/widgets/tool_call_card.dart';

void main() {
  Widget app(Widget child) => MaterialApp(
    theme: esaTheme(brightness: Brightness.dark),
    home: Scaffold(body: child),
  );

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
    expect(find.byType(SelectableText), findsOneWidget);

    await tester.tap(find.text('思考过程'));
    await tester.pumpAndSettle();

    expect(find.byType(SelectableText), findsWidgets);
    expect(find.text('final answer = 42;', findRichText: true), findsOneWidget);
  });

  testWidgets('tool output is selectable', (tester) async {
    await tester.pumpWidget(
      app(const ToolCallCard(name: 'calculator', output: '{"value": 42}')),
    );

    expect(find.byType(SelectableText), findsNWidgets(2));
    expect(find.text('{"value": 42}'), findsOneWidget);
  });
}
