import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/theme/esa_theme.dart';
import 'package:frontend/widgets/composer.dart';

void main() {
  testWidgets('uses the same line metrics for hint and input cursor', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: esaTheme(brightness: Brightness.dark),
        home: Scaffold(body: Composer(busy: false, onSend: (_, _) {})),
      ),
    );

    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.cursorHeight, isNull);
    expect(field.strutStyle, isNull);
    expect(field.decoration?.isCollapsed, isTrue);
    expect(field.decoration?.filled, isFalse);
    expect(field.decoration?.contentPadding, EdgeInsets.zero);
  });

  testWidgets('hides the empty hint while the composer is focused', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: esaTheme(brightness: Brightness.dark),
        home: Scaffold(body: Composer(busy: false, onSend: (_, _) {})),
      ),
    );

    expect(
      tester.widget<TextField>(find.byType(TextField)).decoration?.hintText,
      '向 ESA 提问任何学习问题…',
    );

    await tester.tap(find.byType(TextField));
    await tester.pump();

    expect(
      tester.widget<TextField>(find.byType(TextField)).decoration?.hintText,
      isNull,
    );
  });

  testWidgets('does not send when Enter confirms an IME composition', (
    tester,
  ) async {
    final sent = <String>[];
    await tester.pumpWidget(
      MaterialApp(
        theme: esaTheme(brightness: Brightness.dark),
        home: Scaffold(
          body: Composer(busy: false, onSend: (text, _) => sent.add(text)),
        ),
      ),
    );

    final field = tester.widget<TextField>(find.byType(TextField));
    final controller = field.controller!;
    await tester.showKeyboard(find.byType(TextField));
    controller.value = const TextEditingValue(
      text: 'english',
      selection: TextSelection.collapsed(offset: 7),
      composing: TextRange(start: 0, end: 7),
    );

    await tester.sendKeyDownEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.enter);
    await tester.pump();

    expect(sent, isEmpty);

    controller.value = controller.value.copyWith(composing: TextRange.empty);
    await tester.sendKeyDownEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.enter);
    await tester.pump();

    expect(sent, ['english']);
  });

  testWidgets('hides desktop keyboard shortcuts on narrow screens', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      MaterialApp(
        theme: esaTheme(brightness: Brightness.dark),
        home: Scaffold(body: Composer(busy: false, onSend: (_, _) {})),
      ),
    );

    expect(find.text('Enter 发送 · Shift + Enter 换行'), findsNothing);
    expect(find.bySemanticsLabel('发送'), findsOneWidget);
  });

  testWidgets('inserts an inline LaTeX template at the current selection', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: esaTheme(brightness: Brightness.dark),
        home: Scaffold(body: Composer(busy: false, onSend: (_, _) {})),
      ),
    );

    final field = tester.widget<TextField>(
      find.byKey(const ValueKey('composer-input')),
    );
    field.controller!.value = const TextEditingValue(
      text: '结果是 ',
      selection: TextSelection.collapsed(offset: 4),
    );

    await tester.tap(find.byTooltip('插入公式'));
    await tester.pumpAndSettle();
    expect(find.text('插入 LaTeX 公式'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('latex-template-分数')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('insert-latex')));
    await tester.pumpAndSettle();

    expect(field.controller!.text, r'结果是 $\frac{}{}$');
    expect(field.controller!.selection.extentOffset, 11);
  });

  testWidgets('formula templates compose and insert display math', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: esaTheme(brightness: Brightness.dark),
        home: Scaffold(body: Composer(busy: false, onSend: (_, _) {})),
      ),
    );

    final input = find.byKey(const ValueKey('composer-input'));
    await tester.tap(find.byTooltip('插入公式'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('latex-template-分数')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('latex-template-平方根')));
    await tester.pump();
    await tester.tap(find.text('独立公式'));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('insert-latex')));
    await tester.pumpAndSettle();

    final field = tester.widget<TextField>(input);
    expect(field.controller!.text, contains(r'$$'));
    expect(field.controller!.text, contains(r'\frac{\sqrt{}}{}'));
  });

  testWidgets('composer code preview opens editor and writes changes back', (
    tester,
  ) async {
    final key = GlobalKey<ComposerState>();
    String? blockId;
    String? code;
    String? language;
    await tester.pumpWidget(
      MaterialApp(
        theme: esaTheme(brightness: Brightness.dark),
        home: Scaffold(
          body: Composer(
            key: key,
            busy: false,
            onSend: (_, _) {},
            onOpenCodeEditor: (id, value, syntax) {
              blockId = id;
              code = value;
              language = syntax;
            },
          ),
        ),
      ),
    );

    await tester.enterText(
      find.byKey(const ValueKey('composer-input')),
      '说明\n```python\nvalue = 1\n```',
    );
    await tester.pump();
    await tester.tap(find.byTooltip('在编辑器中打开'));
    await tester.pump();

    expect(blockId, 'composer:0');
    expect(code, 'value = 1');
    expect(language, 'python');

    key.currentState!.replaceCodeBlock('composer:0', 'value = 2');
    await tester.pump();
    final field = tester.widget<TextField>(
      find.byKey(const ValueKey('composer-input')),
    );
    expect(field.controller!.text, '说明\n```python\nvalue = 2\n```');
  });

  testWidgets('composer input changes are reported to the open code editor', (
    tester,
  ) async {
    String? blockId;
    String? code;
    String? language;
    await tester.pumpWidget(
      MaterialApp(
        theme: esaTheme(brightness: Brightness.dark),
        home: Scaffold(
          body: Composer(
            busy: false,
            onSend: (_, _) {},
            onCodeBlockChanged: (id, value, syntax) {
              blockId = id;
              code = value;
              language = syntax;
            },
          ),
        ),
      ),
    );

    await tester.enterText(
      find.byKey(const ValueKey('composer-input')),
      '说明\n```python\nanswer = 42\n```',
    );
    await tester.pump();

    expect(blockId, 'composer:0');
    expect(code, 'answer = 42');
    expect(language, 'python');
  });

  testWidgets('keeps a separate text draft for each conversation', (
    tester,
  ) async {
    String? conversationId = 'conversation-a';
    late void Function(String? value) switchConversation;
    await tester.pumpWidget(
      MaterialApp(
        theme: esaTheme(brightness: Brightness.dark),
        home: StatefulBuilder(
          builder: (context, setState) {
            switchConversation = (value) {
              setState(() => conversationId = value);
            };
            return Scaffold(
              body: Composer(
                busy: false,
                conversationId: conversationId,
                onSend: (_, _) {},
              ),
            );
          },
        ),
      ),
    );

    final input = find.byKey(const ValueKey('composer-input'));
    await tester.enterText(input, '对话 A 的草稿');
    switchConversation('conversation-b');
    await tester.pump();
    expect(tester.widget<TextField>(input).controller!.text, isEmpty);

    await tester.enterText(input, '对话 B 的草稿');
    switchConversation('conversation-a');
    await tester.pump();
    expect(tester.widget<TextField>(input).controller!.text, '对话 A 的草稿');

    switchConversation('conversation-b');
    await tester.pump();
    expect(tester.widget<TextField>(input).controller!.text, '对话 B 的草稿');
  });

  testWidgets('new conversation composer starts empty', (tester) async {
    String? conversationId = 'conversation-a';
    late void Function(String? value) switchConversation;
    await tester.pumpWidget(
      MaterialApp(
        theme: esaTheme(brightness: Brightness.dark),
        home: StatefulBuilder(
          builder: (context, setState) {
            switchConversation = (value) {
              setState(() => conversationId = value);
            };
            return Scaffold(
              body: Composer(
                busy: false,
                conversationId: conversationId,
                onSend: (_, _) {},
              ),
            );
          },
        ),
      ),
    );

    final input = find.byKey(const ValueKey('composer-input'));
    await tester.enterText(input, '已有对话草稿');
    switchConversation(null);
    await tester.pump();
    expect(tester.widget<TextField>(input).controller!.text, isEmpty);
  });
}
