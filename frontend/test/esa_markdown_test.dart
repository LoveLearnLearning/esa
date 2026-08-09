import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:frontend/theme/esa_theme.dart';
import 'package:frontend/widgets/esa_markdown.dart';

void main() {
  Widget app(String data) => MaterialApp(
    theme: esaTheme(brightness: Brightness.dark),
    home: Scaffold(body: EsaMarkdown(data: data, selectable: true)),
  );

  testWidgets('renders fenced code blocks with and without a language', (
    tester,
  ) async {
    await tester.pumpWidget(
      app('''```python
print("hello")
```

```
plain text
```

```some-unknown-language
unknown syntax
```'''),
    );

    expect(find.text('python'), findsOneWidget);
    expect(find.text('plaintext'), findsOneWidget);
    expect(find.text('some-unknown-language'), findsOneWidget);
    // 整条 Markdown 回复共用一个 SelectionArea，才能跨段落和代码块选择。
    expect(find.byType(SelectionArea), findsOneWidget);
    expect(find.byType(SelectableText), findsNothing);
    final markdown = tester.widget<MarkdownBody>(find.byType(MarkdownBody));
    final decoration = markdown.styleSheet!.codeblockDecoration;
    expect(decoration, isA<BoxDecoration>());
    expect((decoration! as BoxDecoration).border, isNull);
    final codeShells = tester.widgetList<Container>(
      find.byWidgetPredicate(
        (widget) =>
            widget is Container &&
            widget.decoration is BoxDecoration &&
            (widget.decoration! as BoxDecoration).color ==
                const Color(0xFF171717),
      ),
    );
    expect(codeShells, hasLength(3));
    expect(codeShells.every((shell) => shell.margin == null), isTrue);
    expect(tester.takeException(), isNull);
  });

  testWidgets('multiple markdown paragraphs share one selection area', (
    tester,
  ) async {
    await tester.pumpWidget(
      app('''第一段文字

第二段文字

- 第三段列表文字'''),
    );

    expect(find.byType(SelectionArea), findsOneWidget);
    expect(find.byType(SelectableText), findsNothing);
    expect(find.text('第一段文字'), findsOneWidget);
    expect(find.text('第二段文字'), findsOneWidget);
    expect(find.text('第三段列表文字'), findsOneWidget);
  });

  testWidgets('code stays highlighted while editing', (tester) async {
    await tester.pumpWidget(
      app('''```dart
// model comment
final answer = 42;
```'''),
    );

    await tester.tap(find.byTooltip('编辑'));
    await tester.pump();

    expect(find.byType(TextField), findsOneWidget);
    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.decoration?.filled, isFalse);
    expect(
      find.ancestor(
        of: find.byType(TextField),
        matching: find.byWidgetPredicate(
          (widget) =>
              widget is SingleChildScrollView &&
              widget.scrollDirection == Axis.horizontal,
        ),
      ),
      findsOneWidget,
    );
    await tester.enterText(find.byType(TextField), 'const answer = 43;');
    await tester.pump();

    expect(find.byTooltip('重置为模型生成内容'), findsOneWidget);
    await tester.tap(find.byTooltip('重置为模型生成内容'));
    await tester.pump();

    expect(
      tester.widget<TextField>(find.byType(TextField)).controller!.text,
      '// model comment\nfinal answer = 42;',
    );
    expect(find.byTooltip('重置为模型生成内容'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('code preview follows streaming markdown updates', (
    tester,
  ) async {
    await tester.pumpWidget(
      app('''```python
print("hel")
```'''),
    );
    expect(find.text('print("hel")', findRichText: true), findsOneWidget);

    await tester.pumpWidget(
      app('''```python
print("hello world")
```'''),
    );
    await tester.pump();

    expect(
      find.text('print("hello world")', findRichText: true),
      findsOneWidget,
    );
    expect(find.text('print("hel")', findRichText: true), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
