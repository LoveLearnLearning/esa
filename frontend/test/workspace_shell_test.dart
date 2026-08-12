import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/pages/home_shell.dart';
import 'package:frontend/state/app_state.dart';
import 'package:frontend/theme/esa_theme.dart';

class _WorkspaceApi extends ApiClient {
  _WorkspaceApi() : super(baseUrl: 'http://test.invalid');

  final List<ResearchProject> projects = [];

  @override
  Future<ScheduleSnapshot> getSchedule() async =>
      const ScheduleSnapshot(courses: [], settings: ScheduleSettings());

  @override
  Future<List<ChatConversation>> listWorkspaceConversations(
    WorkspaceType workspace,
  ) async => const [];

  @override
  Future<List<ResearchProject>> listResearchProjects() async =>
      List.of(projects);

  @override
  Future<List<FrontierTrackingJob>> listFrontierJobs(String projectId) async =>
      const [];

  @override
  Future<List<ResearchDocument>> listResearchDocuments(
    String projectId,
  ) async => const [];

  @override
  Future<List<ResearchDataset>> listResearchDatasets(String projectId) async =>
      const [];

  @override
  Future<ResearchProject> createResearchProject(
    String name,
    String description,
  ) async {
    final project = ResearchProject(
      id: 'project-${projects.length + 1}',
      name: name,
      description: description,
      status: 'active',
      updatedAt: DateTime(2026),
    );
    projects.add(project);
    return project;
  }

  @override
  Future<ChatConversation> createWorkspaceConversation(
    WorkspaceType workspace, {
    String? researchProjectId,
  }) async => ChatConversation(
    id: 'research-chat',
    title: '新对话',
    updatedAt: DateTime(2026),
    workspaceType: workspace,
    researchProjectId: researchProjectId,
  );
}

void main() {
  testWidgets('switches into research workspace and creates a project', (
    tester,
  ) async {
    final api = _WorkspaceApi()
      ..sessionId = 'session'
      ..userId = 'user'
      ..username = 'student';
    final state = AppState(api: api);
    addTearDown(state.dispose);

    await tester.pumpWidget(
      AppScope(
        state: state,
        child: MaterialApp(
          theme: esaTheme(brightness: Brightness.dark),
          home: const HomeShell(),
        ),
      ),
    );
    await tester.pump(const Duration(milliseconds: 200));

    expect(find.byKey(const ValueKey('workspace-switcher')), findsOneWidget);
    await state.switchWorkspace(WorkspaceType.research);
    await tester.pump(const Duration(milliseconds: 300));

    expect(state.activeWorkspace, WorkspaceType.research);
    expect(find.text('科研工作空间'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('new-research-project')));
    await tester.pump(const Duration(milliseconds: 300));
    await tester.enterText(
      find.byKey(const ValueKey('research-project-name')),
      '多智能体科研',
    );
    await tester.enterText(
      find.byKey(const ValueKey('research-project-description')),
      '前沿追踪与论文写作',
    );
    await tester.tap(find.byKey(const ValueKey('create-research-project')));
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.text('多智能体科研'), findsOneWidget);
    expect(find.text('前沿追踪与论文写作'), findsOneWidget);

    await tester.tap(find.text('多智能体科研'));
    await tester.pumpAndSettle();
    expect(find.text('领域前沿追踪'), findsOneWidget);
    expect(find.text('学术写作'), findsOneWidget);
    expect(find.text('数据分析'), findsOneWidget);
    expect(find.text('讲解一道题'), findsNothing);
  });
}
