import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/theme/esa_theme.dart';
import 'package:frontend/widgets/code_editor/code_editor_pane.dart';

void main() {
  test('normalizes common Markdown language aliases', () {
    expect(normalizeCodeLanguage('js'), 'javascript');
    expect(normalizeCodeLanguage('PY'), 'python');
    expect(normalizeCodeLanguage('c++'), 'cpp');
    expect(normalizeCodeLanguage('unknown-language'), 'plaintext');
  });

  testWidgets('editor pane exposes language, reset and close controls', (
    tester,
  ) async {
    var value = 'print(2)';
    var closed = false;
    var sent = false;
    await tester.pumpWidget(
      MaterialApp(
        theme: esaTheme(brightness: Brightness.dark),
        home: Scaffold(
          body: CodeEditorPane(
            value: value,
            originalValue: 'print(1)',
            language: 'python',
            indentSize: 4,
            editorTheme: 'hc-black',
            onChanged: (next) => value = next,
            onLanguageChanged: (_) {},
            onSendToAgent: () => sent = true,
            onClose: () => closed = true,
          ),
        ),
      ),
    );

    expect(find.text('main.py'), findsOneWidget);
    expect(find.text('草稿已保存'), findsOneWidget);
    expect(find.text('本地补全'), findsOneWidget);
    expect(find.text('智能补全 · 括号补全 · 自动缩进'), findsNothing);

    await tester.tap(find.byTooltip('将修改后的代码发送给 Agent'));
    expect(sent, isTrue);

    await tester.tap(find.byTooltip('重置为模型生成内容'));
    await tester.pump();
    expect(value, 'print(1)');

    await tester.tap(find.byTooltip('关闭编辑器'));
    expect(closed, isTrue);
  });
}
