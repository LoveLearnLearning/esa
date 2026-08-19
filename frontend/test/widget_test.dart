// This is a basic Flutter widget test.
//
// To perform an interaction with a widget in your test, use the WidgetTester
// utility in the flutter_test package. For example, you can send tap and scroll
// gestures. You can also use WidgetTester to find child widgets in the widget
// tree, read text, and verify that the values of widget properties are correct.

import 'package:flutter/material.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/main.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/state/app_state.dart';
import 'package:frontend/theme/esa_theme.dart';
import 'package:frontend/widgets/profile_sheet.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _GuestTestApi extends ApiClient {
  _GuestTestApi() : super(baseUrl: 'http://test.invalid');

  @override
  Future<ScheduleSnapshot> getSchedule() async =>
      const ScheduleSnapshot(courses: [], settings: ScheduleSettings());

  @override
  Future<List<LearningCourseSummary>> getLearningCourses() async => const [];
}

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

  testWidgets('restores local code editor settings', (tester) async {
    SharedPreferences.setMockInitialValues({
      'esa.editor.indent_size': 4,
      'esa.editor.theme': 'hc-black',
    });
    final state = AppState(restoringSession: true);
    addTearDown(state.dispose);

    await state.restoreSession();

    expect(state.codeEditorIndentSize, 4);
    expect(state.codeEditorTheme, 'hc-black');
  });

  testWidgets('code editor settings persist locally', (tester) async {
    final state = AppState();
    addTearDown(state.dispose);

    state.setCodeEditorIndentSize(8);
    state.setCodeEditorTheme('vs');
    await tester.pump();
    final preferences = await SharedPreferences.getInstance();

    expect(preferences.getInt('esa.editor.indent_size'), 8);
    expect(preferences.getString('esa.editor.theme'), 'vs');
  });

  testWidgets('settings expose code indentation and editor theme', (
    tester,
  ) async {
    final state = AppState()..enterAsGuest();
    addTearDown(state.dispose);
    await tester.pumpWidget(
      AppScope(
        state: state,
        child: MaterialApp(
          theme: esaTheme(brightness: Brightness.dark),
          home: Builder(
            builder: (context) => Scaffold(
              body: TextButton(
                onPressed: () => showProfileSheet(context),
                child: const Text('打开设置'),
              ),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('打开设置'));
    await tester.pumpAndSettle();

    await tester.ensureVisible(find.text('代码缩进'));
    await tester.pumpAndSettle();
    expect(find.text('代码缩进'), findsOneWidget);
    expect(find.text('代码主题'), findsOneWidget);
    expect(find.text('VS Code 深色'), findsOneWidget);
    await tester.tap(find.text('4'));
    await tester.pump();
    expect(state.codeEditorIndentSize, 4);

    await tester.tap(find.byKey(const ValueKey('code-editor-theme-setting')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('VS Code 浅色').last);
    await tester.pumpAndSettle();
    expect(state.codeEditorTheme, 'vs');
  });

  testWidgets('guest login enters the main shell without a backend session', (
    tester,
  ) async {
    final state = AppState(api: _GuestTestApi());
    addTearDown(state.dispose);
    await tester.pumpWidget(EsaApp(state: state));
    await tester.pump();

    expect(find.text('游客登录'), findsOneWidget);
    await tester.tap(find.text('游客登录'));
    await tester.pumpAndSettle();

    expect(state.username, '游客');
    expect(find.byKey(const ValueKey('learning-home')), findsOneWidget);
    expect(find.text('今天'), findsOneWidget);
    expect(find.textContaining('你好，我是'), findsNothing);
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

    await tester.ensureVisible(accountField);
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

    expect(find.text('ESA-星知智链'), findsOneWidget);
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

    expect(find.text('ESA-星知智链'), findsOneWidget);
    expect(find.text('进入 ESA'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
