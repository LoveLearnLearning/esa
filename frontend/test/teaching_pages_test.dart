import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/pages/student_assignments_page.dart';
import 'package:frontend/pages/teaching_workspace_page.dart';
import 'package:frontend/state/app_state.dart';
import 'package:frontend/theme/esa_theme.dart';

class _TeachingApi extends ApiClient {
  _TeachingApi() : super(baseUrl: 'http://test.invalid');

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
}

class _StudentTeachingApi extends ApiClient {
  _StudentTeachingApi() : super(baseUrl: 'http://test.invalid');

  @override
  Future<List<TeachingClass>> listStudentClasses() async => const [
    TeachingClass(
      id: 'class-1',
      name: '数据结构 1 班',
      course: '数据结构',
      term: '2026 秋',
      status: 'active',
      studentCount: 0,
      openAssignmentCount: 0,
      membershipStatus: 'pending',
      membershipId: 'membership-1',
      teacherUsername: 'teacher',
    ),
  ];

  @override
  Future<List<TeachingAssignment>> listStudentAssignments() async => const [
    TeachingAssignment(
      id: 'assignment-1',
      classId: 'class-1',
      className: '数据结构 1 班',
      course: '数据结构',
      title: '二分查找诊断',
      instructions: '',
      status: 'published',
      totalPoints: 10,
      submittedCount: 0,
      studentCount: 1,
      questions: [],
    ),
  ];
}

Future<void> _pump(WidgetTester tester, ApiClient api, Widget child) async {
  api
    ..sessionId = 'session'
    ..userId = 'user'
    ..username = 'tester';
  final state = AppState(api: api);
  addTearDown(state.dispose);
  await tester.pumpWidget(
    AppScope(
      state: state,
      child: MaterialApp(
        theme: esaTheme(brightness: Brightness.dark),
        home: child,
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('teacher overview shows real work queue and classes', (
    tester,
  ) async {
    await _pump(tester, _TeachingApi(), const TeachingWorkspacePage());

    expect(find.text('教学工作台'), findsOneWidget);
    expect(find.text('数据结构 1 班'), findsOneWidget);
    expect(find.text('待复核'), findsOneWidget);
    expect(find.text('2'), findsOneWidget);
  });

  testWidgets('student center shows invitation and homework', (tester) async {
    await _pump(
      tester,
      _StudentTeachingApi(),
      StudentAssignmentsPage(onOpenChat: (_) async {}),
    );

    expect(find.text('作业中心'), findsOneWidget);
    expect(find.text('接受邀请'), findsOneWidget);
    expect(find.text('二分查找诊断'), findsOneWidget);
    expect(find.text('待完成'), findsOneWidget);
  });
}
