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

class _ReviewApi extends ApiClient {
  _ReviewApi() : super(baseUrl: 'http://test.invalid');

  TeachingSubmission get submission => TeachingSubmission(
    id: 'submission-1',
    assignmentId: 'assignment-1',
    studentId: 'student-1',
    studentUsername: '王小明',
    analysisStatus: 'completed',
    feedbackStatus: 'unpublished',
    answers: [
      TeachingAnswer(
        id: 'answer-1',
        questionId: 'question-1',
        prompt: '解释二分查找的不变量',
        answerText: '目标值始终位于当前搜索区间。',
        maxPoints: 10,
        aiScore: 8,
        feedback: '需要说明边界更新。',
        kpId: 'binary-search',
        raw: const {'ai_error_type': 'boundary'},
      ),
    ],
  );

  @override
  Future<List<TeachingSubmission>> listTeachingSubmissions(String id) async => [
    submission,
  ];

  @override
  Future<TeachingSubmission> getTeachingSubmission(String id) async =>
      submission;
}

/// 班级工作台 mock：dashboard 学情为空（无正式教学证据），
/// 知识点目录来自课程知识图谱接口。
class _ClassWorkspaceApi extends ApiClient {
  _ClassWorkspaceApi({this.knowledgePoints, this.knowledgeError})
    : super(baseUrl: 'http://test.invalid');

  final List<Map<String, dynamic>>? knowledgePoints;
  final String? knowledgeError;

  final List<Map<String, dynamic>> createdAssignments = [];

  @override
  Future<Map<String, dynamic>> getTeachingClass(String classId) async => {
    'class_id': classId,
    'name': '数据结构 1 班',
    'canonical_course': '数据结构',
    'term': '2026 秋',
    'status': 'active',
    'members': const [],
    'assignments': const [],
  };

  @override
  Future<Map<String, dynamic>> getClassDashboard(String classId) async => {
    'student_count': 0,
    'published_evidence_count': 0,
    'knowledge_points': const [],
    'alerts': const [],
  };

  @override
  Future<List<Map<String, dynamic>>> getTeachingClassKnowledgePoints(
    String classId,
  ) async {
    if (knowledgeError != null) throw ApiException(503, knowledgeError!);
    return knowledgePoints ?? const [];
  }

  @override
  Future<TeachingAssignment> createTeachingAssignment({
    required String classId,
    required String title,
    required String instructions,
    required List<Map<String, dynamic>> questions,
    DateTime? dueAt,
  }) async {
    createdAssignments.add({
      'class_id': classId,
      'title': title,
      'questions': questions,
    });
    return TeachingAssignment(
      id: 'assignment-new',
      classId: classId,
      className: '数据结构 1 班',
      course: '数据结构',
      title: title,
      instructions: instructions,
      status: 'draft',
      totalPoints: 10,
      submittedCount: 0,
      studentCount: 0,
      questions: const [],
    );
  }
}

const _classroom = TeachingClass(
  id: 'class-1',
  name: '数据结构 1 班',
  course: '数据结构',
  term: '2026 秋',
);

const _courseKnowledgePoints = [
  {'kp_id': '链表', 'name': '链表'},
  {'kp_id': '顺序表', 'name': '顺序表'},
  {'kp_id': '栈', 'name': '栈'},
  {'kp_id': '队列', 'name': '队列'},
];

Future<void> _openAssignmentDialog(WidgetTester tester, ApiClient api) async {
  await _pump(tester, api, const TeachingClassPage(classroom: _classroom));
  await tester.tap(find.byTooltip('新建作业'));
  await tester.pumpAndSettle();
  expect(find.text('新建诊断作业'), findsOneWidget);
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
    expect(find.text('待复核提交'), findsOneWidget);
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

  testWidgets('teacher review is inline and separates AI from final fields', (
    tester,
  ) async {
    const assignment = TeachingAssignment(
      id: 'assignment-1',
      classId: 'class-1',
      className: '数据结构 1 班',
      course: '数据结构',
      title: '二分查找诊断',
      instructions: '',
      status: 'published',
      totalPoints: 10,
      submittedCount: 1,
      studentCount: 1,
      questions: [],
    );
    await _pump(
      tester,
      _ReviewApi(),
      const TeachingReviewPage(assignment: assignment),
    );

    expect(find.text('王小明'), findsWidgets);
    expect(find.textContaining('AI 建议 8.0 / 10.0'), findsOneWidget);
    expect(find.text('教师得分 / 10.0'), findsOneWidget);
    expect(find.text('错因类型'), findsOneWidget);
    expect(find.text('关联知识点 ID'), findsOneWidget);
    await tester.drag(find.byType(ListView).last, const Offset(0, -600));
    await tester.pumpAndSettle();
    expect(find.text('发布反馈'), findsOneWidget);
    expect(find.byType(AlertDialog), findsNothing);
  });

  testWidgets('assignment dialog offers course knowledge points without evidence', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    // 场景 C：dashboard knowledge_points 为空（无正式教学证据），
    // 作业创建对话框仍显示课程完整知识点，并提交真实 kp_id。
    final api = _ClassWorkspaceApi(knowledgePoints: _courseKnowledgePoints);
    await _openAssignmentDialog(tester, api);

    expect(find.textContaining('正在加载'), findsNothing);
    expect(find.textContaining('知识点加载失败'), findsNothing);
    expect(find.textContaining('暂无知识点'), findsNothing);

    await tester.enterText(
      find.widgetWithText(TextField, '作业标题'),
      '链表入门诊断',
    );
    await tester.enterText(
      find.widgetWithText(TextField, '题目内容'),
      '链表结点包含哪些域？',
    );

    await tester.tap(find.text('不关联知识点'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('链表').last);
    await tester.pumpAndSettle();
    expect(find.text('链表入门诊断'), findsOneWidget);

    await tester.tap(find.text('保存草稿'));
    await tester.pumpAndSettle();

    expect(api.createdAssignments, hasLength(1));
    expect(api.createdAssignments.single['class_id'], 'class-1');
    final questions =
        api.createdAssignments.single['questions'] as List<Map<String, dynamic>>;
    expect(questions.single['kp_id'], '链表');
  });

  testWidgets('assignment dialog shows explicit error when catalog fails', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    // 网络失败与“课程无知识点”分开提示：失败给明确错误和重试入口。
    final api = _ClassWorkspaceApi(knowledgeError: '教学服务暂不可用');
    await _openAssignmentDialog(tester, api);

    expect(find.textContaining('知识点加载失败：教学服务暂不可用'), findsOneWidget);
    expect(find.text('重试'), findsOneWidget);
    expect(find.textContaining('暂无知识点'), findsNothing);
    expect(find.text('不关联知识点'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('assignment dialog distinguishes empty course catalog', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    // 课程确实没有知识点时显示合理空状态，而不是报错。
    final api = _ClassWorkspaceApi(knowledgePoints: const []);
    await _openAssignmentDialog(tester, api);

    expect(find.textContaining('《数据结构》课程暂无知识点'), findsOneWidget);
    expect(find.textContaining('知识点加载失败'), findsNothing);
    expect(find.text('重试'), findsNothing);
    expect(find.text('不关联知识点'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
