import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/pages/role_shell.dart';
import 'package:frontend/state/app_state.dart';
import 'package:frontend/theme/esa_theme.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _RoleShellApi extends ApiClient {
  _RoleShellApi() : super(baseUrl: 'http://test.invalid');

  @override
  Future<ScheduleSnapshot> getSchedule() async =>
      const ScheduleSnapshot(courses: [], settings: ScheduleSettings());

  @override
  Future<Map<String, dynamic>> getTeachingOverview() async => {
    'class_count': 1,
    'pending_review_count': 2,
    'ready_feedback_count': 1,
    'classes': [
      {
        'class_id': 'class-1',
        'name': '数据结构 1 班',
        'canonical_course': '数据结构',
        'term': '2026 秋',
        'status': 'active',
        'student_count': 12,
        'open_assignment_count': 1,
      },
    ],
  };

  @override
  Future<Map<String, dynamic>> getTeachingClass(String classId) async => {
    'class_id': classId,
    'name': '数据结构 1 班',
    'canonical_course': '数据结构',
    'term': '2026 秋',
    'status': 'active',
    'members': const [],
    'assignments': [
      {
        'assignment_id': 'assignment-1',
        'class_id': classId,
        'class_name': '数据结构 1 班',
        'canonical_course': '数据结构',
        'title': '图算法诊断',
        'instructions': '',
        'status': 'published',
        'total_points': 10,
        'submitted_count': 0,
        'student_count': 12,
        'questions': const [],
      },
    ],
  };

  @override
  Future<Map<String, dynamic>> getClassDashboard(String classId) async => {
    'student_count': 12,
    'published_evidence_count': 0,
    'knowledge_points': const [],
    'alerts': const [],
  };

  @override
  Future<List<TeachingSubmission>> listTeachingSubmissions(String id) async =>
      const [];

  @override
  Future<List<ChatConversation>> listWorkspaceConversations(
    WorkspaceType workspace,
  ) async => const [];

  @override
  Future<List<ResearchProject>> listResearchProjects() async => const [];
}

Widget _app(AppState state) => AppScope(
  state: state,
  child: MaterialApp(
    theme: esaTheme(brightness: Brightness.dark),
    home: const RoleShell(),
  ),
);

AppState _state({required bool teacher}) {
  final api = _RoleShellApi()
    ..sessionId = 'session'
    ..userId = 'user'
    ..username = teacher ? 'teacher' : 'student'
    ..accountRole = teacher ? 'teacher' : 'student';
  final state = AppState(api: api);
  if (teacher) {
    state
      ..accountRole = 'teacher'
      ..role = '教师'
      ..availableWorkspaces = const [
        WorkspaceDescriptor(
          type: WorkspaceType.teaching,
          name: '教学空间',
          description: '',
          capabilities: ['chat'],
        ),
        WorkspaceDescriptor(
          type: WorkspaceType.research,
          name: '科研空间',
          description: '',
          capabilities: ['chat', 'research_projects'],
        ),
      ]
      ..activeWorkspace = WorkspaceType.teaching;
  }
  return state;
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('student role renders only the student application shell', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final state = _state(teacher: false);
    addTearDown(state.dispose);
    await tester.pumpWidget(_app(state));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('student-shell')), findsOneWidget);
    expect(find.byKey(const ValueKey('student-global-rail')), findsOneWidget);
    expect(find.byKey(const ValueKey('teacher-shell')), findsNothing);
    expect(find.byKey(const ValueKey('teacher-global-rail')), findsNothing);
    expect(find.text('教学工作台'), findsNothing);
  });

  testWidgets('teacher role renders only the teacher application shell', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final state = _state(teacher: true);
    addTearDown(state.dispose);
    await tester.pumpWidget(_app(state));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('teacher-shell')), findsOneWidget);
    expect(find.byKey(const ValueKey('teacher-global-rail')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('teacher-research-destination')),
      findsNothing,
    );
    expect(find.byKey(const ValueKey('teacher-workbench')), findsOneWidget);
    expect(find.text('教学工作台'), findsWidgets);
    expect(find.text('数据结构 1 班'), findsOneWidget);
    expect(find.byKey(const ValueKey('student-shell')), findsNothing);
    expect(find.byKey(const ValueKey('student-global-rail')), findsNothing);
    expect(find.text('日程'), findsNothing);
    expect(find.text('知识地图'), findsNothing);
    expect(find.text('作业中心'), findsNothing);

    await tester.tap(
      find.byKey(const ValueKey('teacher-assistant-destination')),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('teacher-assistant')), findsOneWidget);
    expect(find.byKey(const ValueKey('composer-input')), findsOneWidget);
  });

  testWidgets('teacher can reach class details and assignment review', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final state = _state(teacher: true);
    addTearDown(state.dispose);
    await tester.pumpWidget(_app(state));
    await tester.pumpAndSettle();

    await tester.tap(find.text('数据结构 1 班'));
    await tester.pumpAndSettle();
    expect(find.byTooltip('邀请学生'), findsOneWidget);
    expect(find.byTooltip('新建作业'), findsOneWidget);
    expect(find.text('图算法诊断'), findsOneWidget);

    await tester.tap(find.text('图算法诊断'));
    await tester.pumpAndSettle();
    expect(find.text('图算法诊断 · 批改'), findsOneWidget);
    expect(find.text('暂无提交'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('teacher mobile shell exposes only teacher destinations', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final state = _state(teacher: true);
    addTearDown(state.dispose);
    await tester.pumpWidget(_app(state));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('teacher-mobile-workbench')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('teacher-mobile-assistant')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('teacher-mobile-research')), findsNothing);
    expect(
      find.byKey(const ValueKey('student-learning-destination')),
      findsNothing,
    );
    expect(find.text('日程'), findsNothing);
    expect(find.text('知识地图'), findsNothing);

    await tester.tap(find.byKey(const ValueKey('teacher-mobile-assistant')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('teacher-assistant')), findsOneWidget);
    expect(find.byKey(const ValueKey('composer-input')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  test('clearing a session removes teacher role and workspace state', () {
    final state = _state(teacher: true);
    addTearDown(state.dispose);

    state.enterAsGuest();

    expect(state.accountRole, 'student');
    expect(state.role, '学生');
    expect(state.activeWorkspace, WorkspaceType.learning);
    expect(state.availableWorkspaces.map((item) => item.type), [
      WorkspaceType.learning,
      WorkspaceType.research,
    ]);
    expect(state.api.accountRole, 'student');
  });
}
