import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/pages/home_shell.dart';
import 'package:frontend/state/app_state.dart';
import 'package:frontend/theme/esa_theme.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _ScheduleApi extends ApiClient {
  _ScheduleApi() : super(baseUrl: 'http://test.invalid');

  final List<ScheduleCourse> courses = [];
  ScheduleSettings settings = const ScheduleSettings();

  @override
  Future<ScheduleSnapshot> getSchedule() async =>
      ScheduleSnapshot(courses: List.of(courses), settings: settings);

  @override
  Future<ScheduleCourse> saveScheduleCourse(ScheduleCourse course) async {
    final index = courses.indexWhere((item) => item.id == course.id);
    index < 0 ? courses.add(course) : courses[index] = course;
    return course;
  }

  @override
  Future<void> deleteScheduleCourse(String courseId) async {
    courses.removeWhere((course) => course.id == courseId);
  }

  @override
  Future<ScheduleSettings> saveScheduleSettings(ScheduleSettings value) async {
    settings = value;
    return value;
  }

  @override
  Future<PersonalKnowledgeBase> getPersonalKnowledgeBase() async =>
      const PersonalKnowledgeBase.empty();

  @override
  Future<List<ChatMessage>> getMessages(String id) async => const [];
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  AppState createState([_ScheduleApi? existingApi]) {
    final api = (existingApi ?? _ScheduleApi())
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
    final api = _ScheduleApi();
    final state = createState(api);
    addTearDown(state.dispose);
    await tester.pumpWidget(app(state));
    await tester.pumpAndSettle();

    expect(find.text('首页'), findsWidgets);
    expect(find.text('对话'), findsNothing);
    expect(find.text('日程'), findsOneWidget);

    await tester.tap(find.text('日程'));
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
    await tester.ensureVisible(
      find.byKey(const ValueKey('save-schedule-settings')),
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

    final restored = createState(api);
    addTearDown(restored.dispose);
    await restored.loadSchedule();
    expect(restored.scheduleCourses.single.name, '数据结构');
    expect(restored.scheduleSettings.periodDurationMinutes, 50);
    expect(restored.scheduleSettings.breakDurationMinutes, 10);
    expect(restored.scheduleSettings.totalPeriods, 10);
  });

  testWidgets('wide layout uses the student workspace rail on the left', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final state = createState();
    addTearDown(state.dispose);
    await tester.pumpWidget(app(state));
    await tester.pumpAndSettle();

    final rail = find.byKey(const ValueKey('student-global-rail'));
    expect(rail, findsOneWidget);
    expect(tester.getRect(rail).center.dx, lessThan(1280 / 2));
    expect(find.text('教学'), findsNothing);

    await tester.tap(find.byTooltip('日程'));
    await tester.pumpAndSettle();
    expect(find.text('添加课程'), findsOneWidget);
  });

  testWidgets(
    'new conversation opens the real chat instead of returning home',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final state = createState();
      addTearDown(state.dispose);
      await tester.pumpWidget(app(state));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('new-conversation')));
      await tester.pumpAndSettle();

      expect(find.byKey(const ValueKey('learning-chat')), findsOneWidget);
      expect(find.byKey(const ValueKey('learning-home')), findsNothing);
    },
  );

  testWidgets('continue learning resumes the latest real conversation', (
    tester,
  ) async {
    final state = createState()
      ..conversations.add(
        ChatConversation(
          id: 'recent-conversation',
          title: '最短路径复习',
          updatedAt: DateTime(2026, 8, 24),
        ),
      );
    addTearDown(state.dispose);
    await tester.pumpWidget(app(state));
    await tester.pumpAndSettle();

    final continueButton = find.widgetWithText(FilledButton, '继续');
    await tester.ensureVisible(continueButton);
    await tester.tap(continueButton);
    await tester.pumpAndSettle();

    expect(state.activeId, 'recent-conversation');
    expect(find.byKey(const ValueKey('learning-chat')), findsOneWidget);
  });

  testWidgets('continue learning is disabled without a course or history', (
    tester,
  ) async {
    final state = createState();
    addTearDown(state.dispose);
    await tester.pumpWidget(app(state));
    await tester.pumpAndSettle();

    final button = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, '继续'),
    );
    expect(button.onPressed, isNull);
  });

  testWidgets('workspace sidebar keeps history and omits primary navigation', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final api = _ScheduleApi()
      ..courses.add(
        const ScheduleCourse(
          id: 'data-structures-1',
          name: '数据结构',
          weekday: 1,
          startPeriod: 1,
          endPeriod: 2,
          startWeek: 1,
          endWeek: 18,
          colorValue: 0xFF2563EB,
        ),
      )
      ..courses.add(
        const ScheduleCourse(
          id: 'data-structures-2',
          name: '数据结构',
          weekday: 3,
          startPeriod: 3,
          endPeriod: 4,
          startWeek: 1,
          endWeek: 18,
          colorValue: 0xFF2563EB,
        ),
      );
    final state = createState(api)
      ..conversations.addAll(
        List.generate(
          8,
          (index) => ChatConversation(
            id: 'history-$index',
            title: '历史对话 ${index + 1}',
            updatedAt: DateTime(2026, 8, 14, 12, 0, index),
          ),
        ),
      );
    addTearDown(state.dispose);

    await tester.pumpWidget(app(state));
    await tester.pumpAndSettle();

    expect(find.text('最近对话'), findsNothing);
    expect(
      find.byKey(const ValueKey('workspace-history-heading')),
      findsOneWidget,
    );
    expect(find.text('历史对话 7'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('workspace-courses-heading')),
      findsNothing,
    );
    expect(find.text('作业'), findsNothing);
    expect(find.text('日程'), findsNothing);
    expect(find.text('知识地图'), findsNothing);
  });

  testWidgets(
    'desktop home uses the practical four-column information layout',
    (tester) async {
      tester.view.physicalSize = const Size(1440, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final state = createState()
        ..learningCourses = const [
          LearningCourseSummary(
            name: '数据结构与算法',
            totalPoints: 12,
            evaluatedPoints: 8,
            weakPoints: 2,
            reviewPoints: 1,
            averageMastery: 62,
          ),
        ]
        ..masteryReport = const MasteryReport(
          totalPoints: 12,
          averageMastery: 62,
          weakPoints: [MasteryPoint(name: 'Dijkstra', masteryLevel: 45)],
          strongPoints: [],
          stalePoints: [MasteryPoint(name: '最短路径', masteryLevel: 58)],
        );
      addTearDown(state.dispose);
      await tester.pumpWidget(app(state));
      await tester.pumpAndSettle();

      expect(find.byKey(const ValueKey('learning-home')), findsOneWidget);
      expect(find.text('继续学习'), findsWidgets);
      expect(find.text('待办'), findsOneWidget);
      expect(find.text('最近'), findsOneWidget);
      expect(find.textContaining('你好，我是'), findsNothing);
      expect(find.text('生成复习计划'), findsNothing);
      expect(find.text('附件'), findsOneWidget);
      expect(find.text('Markdown'), findsOneWidget);
      expect(find.text('LaTeX'), findsOneWidget);
      expect(
        find.byKey(const ValueKey('learning-context-panel')),
        findsOneWidget,
      );
      expect(find.text('当前上下文'), findsOneWidget);
      expect(find.text('已选资料 0'), findsOneWidget);
      expect(find.text('引用课程资料'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'medium desktop hides context first and keeps sidebar collapsible',
    (tester) async {
      tester.view.physicalSize = const Size(1100, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final state = createState();
      addTearDown(state.dispose);
      await tester.pumpWidget(app(state));
      await tester.pumpAndSettle();

      expect(find.byKey(const ValueKey('learning-home')), findsOneWidget);
      expect(
        find.byKey(const ValueKey('learning-context-panel')),
        findsNothing,
      );
      expect(find.text('学习空间'), findsOneWidget);

      await tester.tap(find.byTooltip('收起侧栏'));
      await tester.pumpAndSettle();
      expect(find.text('学习空间'), findsNothing);
      expect(find.byTooltip('展开侧栏'), findsOneWidget);
      expect(tester.takeException(), isNull);

      await tester.tap(find.byTooltip('展开侧栏'));
      await tester.pumpAndSettle();
      expect(find.text('学习空间'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('narrow timetable keeps the complete seven-day grid visible', (
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
    await state.saveScheduleCourse(
      const ScheduleCourse(
        id: 'mobile-course-2',
        name: '操作系统',
        weekday: 2,
        startPeriod: 3,
        endPeriod: 4,
        startWeek: 1,
        endWeek: 18,
        colorValue: 0xFF7C3AED,
      ),
    );

    await tester.pumpWidget(app(state));
    await tester.pumpAndSettle();
    await tester.tap(find.text('日程'));
    await tester.pumpAndSettle();
    expect(find.text('高等数学'), findsOneWidget);
    expect(find.text('操作系统'), findsOneWidget);
    expect(find.byKey(const ValueKey('schedule-week-grid')), findsOneWidget);
    expect(find.byKey(const ValueKey('schedule-weekday-1')), findsOneWidget);
    expect(find.byKey(const ValueKey('schedule-weekday-7')), findsOneWidget);
    final gridRect = tester.getRect(
      find.byKey(const ValueKey('schedule-week-grid')),
    );
    expect(
      tester.getRect(find.byKey(const ValueKey('schedule-weekday-7'))).right,
      lessThanOrEqualTo(gridRect.right + 0.01),
    );
    expect(tester.getSize(find.text('高等数学')).width, lessThan(48));
    expect(find.text('08:00'), findsOneWidget);
    expect(find.text('09:40'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('schedule-import-button')),
      findsOneWidget,
    );

    expect(find.text('第 1 周'), findsOneWidget);
    await tester.fling(find.text('高等数学'), const Offset(-320, 0), 1000);
    await tester.pumpAndSettle();
    expect(find.text('第 2 周'), findsOneWidget);
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

  testWidgets('student mobile navigation exposes the personal knowledge base', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final state = createState();
    addTearDown(state.dispose);
    await tester.pumpWidget(app(state));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('student-learning-destination')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('student-research-destination')),
      findsOneWidget,
    );
    await tester.tap(find.text('资料库'));
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('personal-knowledge-base-page')),
      findsOneWidget,
    );
    expect(find.text('教学'), findsNothing);
  });

  testWidgets('student mobile assistant can open the history drawer', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final state = createState();
    addTearDown(state.dispose);
    await tester.pumpWidget(app(state));
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('历史对话'));
    await tester.pumpAndSettle();

    expect(find.text('搜索历史对话'), findsOneWidget);
    expect(find.text('开启新对话'), findsOneWidget);
  });
}
