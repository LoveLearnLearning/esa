import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/pages/home_shell.dart';
import 'package:frontend/state/app_state.dart';
import 'package:frontend/theme/esa_theme.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _KeyboardApi extends ApiClient {
  _KeyboardApi() : super(baseUrl: 'http://test.invalid');

  @override
  Future<ScheduleSnapshot> getSchedule() async =>
      const ScheduleSnapshot(courses: [], settings: ScheduleSettings());

  @override
  Future<List<ChatConversation>> listConversations() async => const [];

  @override
  Future<List<ChatMessage>> getMessages(String id) async => const [];

  @override
  Future<PersonalKnowledgeBase> getPersonalKnowledgeBase({
    String? knowledgeBaseId,
  }) async => const PersonalKnowledgeBase.empty();
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  AppState createState(_KeyboardApi api) {
    final state = AppState(api: api)
      ..conversations.add(
        ChatConversation(
          id: 'keyboard-chat',
          title: '键盘测试',
          updatedAt: DateTime(2026),
        ),
      );
    return state;
  }

  // 用可变的 MediaQuery.viewInsets 模拟软键盘弹出/收起。
  Widget app(AppState state, ValueNotifier<EdgeInsets> keyboardInsets) =>
      ValueListenableBuilder<EdgeInsets>(
        valueListenable: keyboardInsets,
        builder: (context, insets, _) => AppScope(
          state: state,
          child: MaterialApp(
            theme: esaTheme(brightness: Brightness.dark),
            home: MediaQuery(
              data: MediaQueryData(
                size: const Size(390, 844),
                devicePixelRatio: 1,
                textScaler: TextScaler.noScaling,
                platformBrightness: Brightness.dark,
                viewInsets: insets,
                padding: EdgeInsets.zero,
                viewPadding: EdgeInsets.zero,
                systemGestureInsets: EdgeInsets.zero,
              ),
              child: const HomeShell(),
            ),
          ),
        ),
      );

  testWidgets(
    'mobile keyboard dismiss restores content height and bottom bar',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final keyboardInsets = ValueNotifier<EdgeInsets>(EdgeInsets.zero);
      addTearDown(keyboardInsets.dispose);

      final api = _KeyboardApi()
        ..sessionId = 'session'
        ..userId = 'user-1'
        ..username = 'tester';
      final state = createState(api);
      addTearDown(state.dispose);
      await tester.pumpWidget(app(state, keyboardInsets));
      await tester.pumpAndSettle();

      // 进入对话界面
      final continueButton = find.byKey(
        const ValueKey('continue-learning-action'),
      );
      await tester.ensureVisible(continueButton);
      await tester.tap(continueButton);
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('learning-chat')), findsOneWidget);

      final bottomBarKey = find.byKey(
        const ValueKey('student-learning-destination'),
      );
      final chatKey = find.byKey(const ValueKey('learning-chat'));

      // 键盘弹出：内容区被压缩、底部导航隐藏
      keyboardInsets.value = const EdgeInsets.only(bottom: 300);
      await tester.pumpAndSettle();
      final chatUp = tester.getSize(chatKey);
      expect(chatUp.height, lessThan(600), reason: '键盘弹出时内容区应被压缩（输入框不被键盘遮挡）');
      expect(bottomBarKey, findsNothing, reason: '键盘弹出时底部导航应隐藏');

      // 键盘收起（不点发送，直接收起）：内容区恢复、底部导航恢复贴底
      keyboardInsets.value = EdgeInsets.zero;
      await tester.pumpAndSettle();
      for (var i = 0; i < 5; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      await tester.pumpAndSettle();

      final chatAfter = tester.getSize(chatKey);
      final barBottom = tester.getBottomLeft(bottomBarKey).dy;
      expect(
        chatAfter.height,
        greaterThan(chatUp.height),
        reason: '键盘收起后内容区高度应恢复（不残留键盘压缩 → 不顶起/黑屏）',
      );
      expect(bottomBarKey, findsOneWidget, reason: '键盘收起后底部导航应恢复显示');
      expect(barBottom, closeTo(844, 1), reason: '键盘收起后底部导航应贴回屏幕底部（无黑屏留白）');
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('home composer stays visible above the software keyboard', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final keyboardInsets = ValueNotifier<EdgeInsets>(EdgeInsets.zero);
    addTearDown(keyboardInsets.dispose);
    final api = _KeyboardApi()
      ..sessionId = 'session'
      ..userId = 'user-1'
      ..username = 'tester';
    final state = createState(api);
    addTearDown(state.dispose);
    await tester.pumpWidget(app(state, keyboardInsets));
    await tester.pumpAndSettle();

    final composer = find.byKey(const ValueKey('mobile-home-composer'));
    final input = find.byKey(const ValueKey('composer-input'));
    expect(composer, findsOneWidget);
    expect(input, findsOneWidget);

    await tester.tap(input);
    keyboardInsets.value = const EdgeInsets.only(bottom: 300);
    await tester.pumpAndSettle();

    expect(composer, findsOneWidget);
    expect(
      tester.getRect(composer).bottom,
      lessThanOrEqualTo(544),
      reason: '首页输入框必须随 300px 软键盘上移并完整保留在可视区域内',
    );
    expect(
      find.byKey(const ValueKey('student-learning-destination')),
      findsNothing,
      reason: '键盘弹出时底部导航应让出输入空间',
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('keyboard dismiss releases composer focus via didChangeMetrics', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final api = _KeyboardApi()
      ..sessionId = 'session'
      ..userId = 'user-1'
      ..username = 'tester';
    final state = createState(api);
    addTearDown(state.dispose);
    final keyboardInsets = ValueNotifier<EdgeInsets>(EdgeInsets.zero);
    addTearDown(keyboardInsets.dispose);
    await tester.pumpWidget(app(state, keyboardInsets));
    await tester.pumpAndSettle();

    final continueButton = find.byKey(
      const ValueKey('continue-learning-action'),
    );
    await tester.ensureVisible(continueButton);
    await tester.tap(continueButton);
    await tester.pumpAndSettle();

    final composerInput = find.byKey(const ValueKey('composer-input'));
    await tester.tap(composerInput);
    await tester.pump();
    expect(tester.widget<TextField>(composerInput).focusNode?.hasFocus, isTrue);

    // 键盘弹出（用 tester.view.viewInsets 更新 platformDispatcher，
    // 使 didChangeMetrics 能感知真实 viewInsets 变化）
    tester.view.viewInsets = const FakeViewPadding(bottom: 300);
    await tester.pumpAndSettle();

    // 键盘收起（不点发送）：didChangeMetrics 应释放输入框焦点，
    // 避免焦点残留导致 viewInsets 不归零、页面顶起黑屏
    tester.view.resetViewInsets();
    tester.binding.handleMetricsChanged();
    await tester.pumpAndSettle();
    await tester.pump();

    final focusAfter = tester
        .widget<TextField>(composerInput)
        .focusNode
        ?.hasFocus;
    expect(
      focusAfter,
      isFalse,
      reason:
          '直接收起键盘后应释放输入框焦点，'
          '确保浏览器 viewInsets 归零、页面正常回落',
    );
    expect(tester.takeException(), isNull);
  });
}
