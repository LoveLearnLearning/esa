import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/theme/esa_theme.dart';
import 'package:frontend/widgets/composer.dart';

void main() {
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
}
