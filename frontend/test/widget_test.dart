// This is a basic Flutter widget test.
//
// To perform an interaction with a widget in your test, use the WidgetTester
// utility in the flutter_test package. For example, you can send tap and scroll
// gestures. You can also use WidgetTester to find child widgets in the widget
// tree, read text, and verify that the values of widget properties are correct.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('shows login form when signed out', (tester) async {
    await tester.pumpWidget(const EsaApp());
    await tester.pump();

    expect(find.text('登录'), findsWidgets);
    expect(find.text('用户名'), findsOneWidget);
    expect(find.text('密码'), findsOneWidget);
    expect(find.text('记住登录'), findsOneWidget);
  });

  testWidgets('submits login form from password keyboard action', (
    tester,
  ) async {
    await tester.pumpWidget(const EsaApp());
    await tester.pump();

    final fields = find.byType(EditableText);
    await tester.enterText(fields.at(0), 'feng');
    await tester.enterText(fields.at(1), 'short');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pump();

    expect(find.text('密码至少 8 位'), findsOneWidget);
  });
}
