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
      '问点什么…',
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
    expect(find.text('发送'), findsOneWidget);
  });
}
