import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/pages/home_shell.dart';
import 'package:frontend/state/app_state.dart';
import 'package:frontend/theme/esa_theme.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  AppState createState() {
    final api = ApiClient(baseUrl: 'http://test.invalid')
      ..sessionId = 'session'
      ..userId = 'user-1'
      ..username = 'tester';
    return AppState(api: api);
  }

  Widget app(AppState state) => AppScope(
    state: state,
    child: MaterialApp(
      theme: esaTheme(brightness: Brightness.dark),
      home: const HomeShell(),
    ),
  );

  testWidgets('bottom navigation opens the timetable and adds a course', (
    tester,
  ) async {
    final state = createState();
    addTearDown(state.dispose);
    await tester.pumpWidget(app(state));
    await tester.pumpAndSettle();

    expect(find.text('学习助手'), findsOneWidget);
    expect(find.text('课表'), findsOneWidget);

    await tester.tap(find.text('课表'));
    await tester.pumpAndSettle();
    expect(find.text('添加课程'), findsOneWidget);
    final gridRect = tester.getRect(
      find.byKey(const ValueKey('schedule-week-grid')),
    );
    final cardRect = tester.getRect(
      find.byKey(const ValueKey('schedule-week-card')),
    );
    final viewportWidth =
        tester.view.physicalSize.width / tester.view.devicePixelRatio;
    expect(cardRect.left, greaterThanOrEqualTo(18));
    expect(cardRect.right, lessThanOrEqualTo(viewportWidth - 18));
    expect(gridRect.left, greaterThan(cardRect.left));
    expect(gridRect.right, lessThan(cardRect.right));
    expect(
      tester.getRect(find.byKey(const ValueKey('schedule-weekday-7'))).right,
      lessThanOrEqualTo(gridRect.right + 0.01),
    );

    await tester.tap(find.byKey(const ValueKey('schedule-settings-button')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('schedule-morning-count')),
      '5',
    );
    await tester.enterText(
      find.byKey(const ValueKey('schedule-afternoon-count')),
      '3',
    );
    await tester.enterText(
      find.byKey(const ValueKey('schedule-evening-count')),
      '2',
    );
    await tester.enterText(
      find.byKey(const ValueKey('schedule-period-duration')),
      '50',
    );
    await tester.enterText(
      find.byKey(const ValueKey('schedule-break-duration')),
      '10',
    );
    await tester.tap(find.byKey(const ValueKey('save-schedule-settings')));
    await tester.pumpAndSettle();

    expect(state.scheduleSettings.periodDurationMinutes, 50);
    expect(state.scheduleSettings.breakDurationMinutes, 10);
    expect(state.scheduleSettings.morningPeriodCount, 5);
    expect(state.scheduleSettings.afternoonPeriodCount, 3);
    expect(state.scheduleSettings.eveningPeriodCount, 2);

    await tester.tap(find.text('添加课程'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('schedule-course-name')),
      '数据结构',
    );
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();

    expect(find.text('数据结构'), findsOneWidget);
    expect(find.text('08:00'), findsOneWidget);
    expect(find.text('09:50'), findsOneWidget);
    expect(state.scheduleCourses, hasLength(1));

    final restored = createState();
    addTearDown(restored.dispose);
    await restored.loadSchedule();
    expect(restored.scheduleCourses.single.name, '数据结构');
    expect(restored.scheduleSettings.periodDurationMinutes, 50);
    expect(restored.scheduleSettings.breakDurationMinutes, 10);
    expect(restored.scheduleSettings.totalPeriods, 10);
  });

  testWidgets('narrow timetable shows course times without overflowing', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final state = createState();
    addTearDown(state.dispose);
    await state.saveScheduleCourse(
      const ScheduleCourse(
        id: 'mobile-course',
        name: '高等数学',
        weekday: 1,
        startPeriod: 1,
        endPeriod: 2,
        startWeek: 1,
        endWeek: 18,
        colorValue: 0xFF2563EB,
      ),
    );

    await tester.pumpWidget(app(state));
    await tester.pumpAndSettle();
    await tester.tap(find.text('课表'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('周一'));
    await tester.pumpAndSettle();

    expect(find.text('高等数学'), findsOneWidget);
    expect(find.text('08:00–09:40'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('schedule-settings-button')),
      findsOneWidget,
    );
    await tester.tap(find.byKey(const ValueKey('schedule-settings-button')));
    await tester.pumpAndSettle();
    expect(find.text('上午'), findsOneWidget);
    expect(find.text('下午'), findsOneWidget);
    expect(find.text('晚上'), findsOneWidget);
  });
}
