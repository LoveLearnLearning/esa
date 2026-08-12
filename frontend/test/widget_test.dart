// This is a basic Flutter widget test.
//
// To perform an interaction with a widget in your test, use the WidgetTester
// utility in the flutter_test package. For example, you can send tap and scroll
// gestures. You can also use WidgetTester to find child widgets in the widget
// tree, read text, and verify that the values of widget properties are correct.

import 'package:flutter/material.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/main.dart';
import 'package:frontend/state/app_state.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('shows login form when signed out', (tester) async {
    await tester.pumpWidget(const EsaApp());
    await tester.pump();

    expect(find.text('登录'), findsWidgets);
    expect(find.text('邮箱或用户名'), findsOneWidget);
    expect(find.text('密码'), findsOneWidget);
    expect(find.text('记住登录'), findsOneWidget);
  });

  testWidgets('renders a startup page while the remembered session loads', (
    tester,
  ) async {
    final state = AppState(restoringSession: true);

    await tester.pumpWidget(EsaApp(state: state));

    expect(find.text('星知智链'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    await state.restoreSession();
    await tester.pump();

    expect(find.text('邮箱或用户名'), findsOneWidget);
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

  testWidgets('hides the input hint as soon as the field is focused', (
    tester,
  ) async {
    await tester.pumpWidget(const EsaApp());
    await tester.pump();

    final accountField = find.byType(TextField).first;
    expect(
      tester.widget<TextField>(accountField).decoration?.hintText,
      'name@example.com',
    );

    await tester.tap(accountField);
    await tester.pump();

    expect(tester.widget<TextField>(accountField).decoration?.hintText, isNull);
  });

  testWidgets('registration requires email and verification code', (
    tester,
  ) async {
    await tester.pumpWidget(const EsaApp());
    await tester.pump();

    await tester.tap(find.text('注册').first);
    await tester.pump();

    expect(find.text('邮箱'), findsOneWidget);
    expect(find.text('邮箱验证码'), findsOneWidget);
    expect(find.text('获取验证码'), findsOneWidget);
    expect(find.text('用户名'), findsOneWidget);
    expect(find.text('确认密码'), findsOneWidget);
  });

  testWidgets('auth page renders without overflow on desktop', (tester) async {
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(const EsaApp());
    await tester.pump();

    expect(find.text('Your knowledge\nis a network.'), findsOneWidget);
    expect(find.text('欢迎回来'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('desktop knowledge graph responds to mouse movement', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(const EsaApp());
    final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
    addTearDown(mouse.removePointer);
    await mouse.addPointer(location: const Offset(120, 180));
    await mouse.moveTo(const Offset(460, 310));
    await tester.pump(const Duration(milliseconds: 80));
    await mouse.moveTo(const Offset(720, 520));
    await tester.pump(const Duration(milliseconds: 80));

    expect(tester.takeException(), isNull);
  });

  testWidgets('auth page renders without overflow on mobile', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(const EsaApp());
    await tester.pump();

    expect(find.text('Your knowledge is a network.'), findsOneWidget);
    expect(find.text('进入 ESA'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
