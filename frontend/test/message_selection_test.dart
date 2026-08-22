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

  testWidgets('code block can open the page-level editor', (tester) async {
    final message = ChatMessage(
      id: 'assistant-code-editor',
      role: MessageRole.assistant,
      text: '''```python
print("hello")
```''',
    );
    String? code;
    String? language;

    await tester.pumpWidget(
      app(
        AssistantMessage(
          message: message,
          onRegenerate: () {},
          onOpenCodeEditor: (value, syntax) {
            code = value.trim();
            language = syntax;
          },
        ),
      ),
    );

    await tester.tap(find.byTooltip('在编辑器中打开'));
    await tester.pump();

    expect(code, 'print("hello")');
    expect(language, 'python');
  });

  testWidgets('user code block opens the page-level editor with its block id', (
    tester,
  ) async {
    String? blockId;
    String? code;
    String? language;
    await tester.pumpWidget(
      app(
        UserBubble(
          text: '''用户代码：
```dart
final answer = 42;
```''',
          codeBlockPrefix: 'user-message',
          onOpenCodeEditorWithId: (id, value, syntax) {
            blockId = id;
            code = value;
            language = syntax;
          },
        ),
      ),
    );

    await tester.tap(find.byTooltip('在编辑器中打开'));
    await tester.pump();

    expect(blockId, 'user-message:0');
    expect(code, 'final answer = 42;');
    expect(language, 'dart');
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

  testWidgets('assistant renders source badges after text and opens them', (
    tester,
  ) async {
    SourceCitation? opened;
    final message = ChatMessage(
      id: 'assistant-source',
      role: MessageRole.assistant,
      text: '回答内容\n\n【来源 1 | 个人知识库】',
    );

    await tester.pumpWidget(
      app(
        AssistantMessage(
          message: message,
          onRegenerate: () {},
          sources: const [
            SourceCitation(
              index: 1,
              label: '来源 1',
              filename: 'lecture.pdf',
              page: 3,
            ),
          ],
          onOpenSource: (value) => opened = value,
        ),
      ),
    );

    expect(find.textContaining('【来源'), findsNothing);
    expect(find.text('lecture.pdf · 第3页'), findsOneWidget);
    await tester.tap(find.text('lecture.pdf · 第3页'));
    expect(opened?.filename, 'lecture.pdf');
    expect(opened?.page, 3);
  });

  testWidgets('public retrieval source badges are also clickable', (
    tester,
  ) async {
    SourceCitation? opened;
    final message = ChatMessage(
      id: 'assistant-public-source',
      role: MessageRole.assistant,
      text: '回答内容',
    );

    await tester.pumpWidget(
      app(
        AssistantMessage(
          message: message,
          onRegenerate: () {},
          sources: const [
            SourceCitation(
              index: 1,
              label: '来源 1 · calculus.pdf',
              filename: 'calculus.pdf',
              page: 12,
            ),
          ],
          onOpenSource: (value) => opened = value,
        ),
      ),
    );

    await tester.tap(find.text('calculus.pdf · 第12页'));
    expect(opened?.filename, 'calculus.pdf');
    expect(opened?.page, 12);
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

    message.text = '实';
    message.notifyListeners();
    message.text += '时生成';
    message.notifyListeners();
    await tester.pump(const Duration(milliseconds: 130));
    expect(find.text('实时生成'), findsOneWidget);
    expect(contentChanges, 1);

    message.typing = false;
    message.notifyListeners();
    await tester.pump(const Duration(milliseconds: 130));
    expect(find.byType(SelectionArea), findsOneWidget);
  });

  testWidgets(
    'stream rendering pauses while reading and catches up on resume',
    (tester) async {
      final message = ChatMessage.typingPlaceholder();
      final renderPaused = ValueNotifier(true);
      addTearDown(renderPaused.dispose);

      await tester.pumpWidget(
        app(
          AssistantMessage(
            message: message,
            renderPaused: renderPaused,
            onRegenerate: () {},
          ),
        ),
      );

      message.text = '后台继续接收的内容';
      message.notifyListeners();
      await tester.pump(const Duration(milliseconds: 250));
      expect(find.text('后台继续接收的内容'), findsNothing);

      renderPaused.value = false;
      await tester.pump(const Duration(milliseconds: 1));
      expect(find.text('后台继续接收的内容'), findsOneWidget);
      expect(find.byType(SelectionArea), findsNothing);

      message.typing = false;
      message.notifyListeners();
      await tester.pump(const Duration(milliseconds: 130));
      expect(find.byType(SelectionArea), findsOneWidget);
    },
  );

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

  testWidgets('user attachment opens its preview callback', (tester) async {
    const attachment = DocumentAttachment(
      id: 'attachment-1',
      filename: '研究笔记.pdf',
      mode: 'pending',
      tokenCount: 0,
      elementCount: 0,
      pageCount: 4,
      validationStatus: 'ready',
      qualityIssueCount: 0,
      mediaType: 'application/pdf',
      sizeBytes: 1024,
    );
    DocumentAttachment? opened;
    await tester.pumpWidget(
      app(
        UserBubble(
          text: '请阅读这个文件',
          attachments: const [attachment],
          onOpenAttachment: (value) => opened = value,
        ),
      ),
    );

    expect(find.text('研究笔记.pdf'), findsOneWidget);
    await tester.tap(find.text('研究笔记.pdf'));
    await tester.pump();

    expect(opened, same(attachment));
  });

  testWidgets('user message can be edited and resent', (tester) async {
    String? edited;
    await tester.pumpWidget(
      app(UserBubble(text: '旧问题', onEdit: (value) async => edited = value)),
    );

    await tester.tap(find.byTooltip('编辑消息'));
    await tester.pump();
    await tester.enterText(find.byType(TextField), '修改后的问题');
    await tester.tap(find.text('重新发送'));
    await tester.pump();

    expect(edited, '修改后的问题');
    expect(find.byType(TextField), findsNothing);
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

  testWidgets('completed tool output is collapsed until expanded', (
    tester,
  ) async {
    await tester.pumpWidget(
      app(const ToolCallCard(name: 'calculator', output: '{"value": 42}')),
    );

    expect(find.byType(SelectableText), findsNothing);
    expect(find.text('{"value": 42}'), findsNothing);

    await tester.tap(find.text('TOOL · calculator'));
    await tester.pumpAndSettle();

    expect(find.byType(SelectableText), findsOneWidget);
    expect(find.text('{"value": 42}'), findsOneWidget);
  });

  testWidgets('running tool is expanded with a progress indicator', (
    tester,
  ) async {
    await tester.pumpWidget(
      app(
        const ToolCallCard(
          name: 'parse_pdf_attachment',
          output: '',
          running: true,
        ),
      ),
    );

    expect(find.text('调用中'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(find.text('正在执行 parse_pdf_attachment…'), findsOneWidget);
  });

  testWidgets('tool collapses automatically when the call completes', (
    tester,
  ) async {
    await tester.pumpWidget(
      app(
        const ToolCallCard(
          name: 'parse_pdf_attachment',
          output: '',
          running: true,
        ),
      ),
    );

    await tester.pumpWidget(
      app(const ToolCallCard(name: 'parse_pdf_attachment', output: '解析完成')),
    );
    await tester.pumpAndSettle();

    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.text('解析完成'), findsNothing);

    await tester.tap(find.text('TOOL · parse_pdf_attachment'));
    await tester.pumpAndSettle();

    expect(find.text('解析完成'), findsOneWidget);
  });
}
