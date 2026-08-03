import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
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
    expect(find.byType(SelectableText), findsNWidgets(3));
    expect(tester.takeException(), isNull);
  });

  testWidgets('code stays highlighted while editing', (tester) async {
    await tester.pumpWidget(
      app('''```dart
final answer = 42;
```'''),
    );

    await tester.tap(find.byTooltip('编辑'));
    await tester.pump();

    expect(find.byType(TextField), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'const answer = 43;');
    await tester.pump();
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
    expect(find.text('print("hel")'), findsOneWidget);

    await tester.pumpWidget(
      app('''```python
print("hello world")
```'''),
    );
    await tester.pump();

    expect(find.text('print("hello world")'), findsOneWidget);
    expect(find.text('print("hel")'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
