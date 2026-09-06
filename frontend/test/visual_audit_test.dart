import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/pages/home_shell.dart';
import 'package:frontend/state/app_state.dart';
import 'package:frontend/theme/esa_theme.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _VisualApi extends ApiClient {
  _VisualApi({this.withConversation = false})
    : super(baseUrl: 'http://test.invalid');

  final bool withConversation;

  static final project = ResearchProject(
    id: 'mci',
    name: 'MCI 多模态识别',
    description: '整合神经影像、认知量表与生物标志物数据，构建可解释的 MCI 识别模型',
    status: 'active',
    updatedAt: DateTime(2026),
    documentCount: 12,
  );

  @override
  Future<PlannerSnapshot> getPlanner() async => const PlannerSnapshot();

  @override
  Future<ScheduleSnapshot> getSchedule() async => const ScheduleSnapshot(
    courses: [
      ScheduleCourse(
        id: 'schedule-algorithms',
        name: '数据结构与算法',
        weekday: 3,
        startPeriod: 1,
        endPeriod: 2,
        startWeek: 1,
        endWeek: 18,
        colorValue: 0xFF4F7FF7,
        teacher: '陈老师',
        location: '东九楼 D202',
      ),
      ScheduleCourse(
        id: 'schedule-os',
        name: '操作系统原理与实践',
        weekday: 4,
        startPeriod: 3,
        endPeriod: 4,
        startWeek: 1,
        endWeek: 18,
        colorValue: 0xFF5E8B75,
        teacher: '李老师',
        location: '南一楼 307',
      ),
    ],
    settings: ScheduleSettings(),
  );

  @override
  Future<List<ChatConversation>> listWorkspaceConversations(
    WorkspaceType workspace,
  ) async => _conversations(workspace);

  @override
  Future<List<ChatConversation>> listConversations() async =>
      _conversations(WorkspaceType.learning);

  List<ChatConversation> _conversations(WorkspaceType workspace) =>
      withConversation && workspace == WorkspaceType.learning
      ? [
          ChatConversation(
            id: 'chat',
            title: '洛必达法则怎么用',
            updatedAt: DateTime(2026),
          ),
        ]
      : const [];

  @override
  Future<List<ChatMessage>> getMessages(String id) async => [
    ChatMessage(
      id: 'question',
      role: MessageRole.user,
      text: '洛必达法则怎么用？能结合例子详细讲解一下吗？',
    ),
    ChatMessage(
      id: 'answer',
      role: MessageRole.assistant,
      text: '''当然可以！洛必达法则用于求解未定式极限，它的核心思想是：

当函数在某点趋于零或趋于无穷，且直接代入会得到 0/0 或无穷/无穷时，可以分别对分子和分母求导，再求导数之比的极限。

## 适用条件
- 分子与分母在去心邻域内可导；
- 分母的导数不为零；
- 导数之比的极限存在。

## 例题 1（0/0 型）
求极限：sin(x) / x，当 x 趋近于 0。

分别求导后得到 cos(x) / 1，因此极限为 1。

## 例题 2（无穷/无穷型）
求极限：ln(x) / x，当 x 趋近于无穷。

分别求导后得到 1/x，因此极限为 0。''',
    ),
  ];

  @override
  Future<List<LearningCourseSummary>> getLearningCourses() async => const [
    LearningCourseSummary(
      name: '高等数学',
      totalPoints: 8,
      evaluatedPoints: 8,
      weakPoints: 2,
      reviewPoints: 3,
      averageMastery: 72,
    ),
  ];

  @override
  Future<KnowledgeMapData> getKnowledgeMap(String course) async {
    const names = ['导数', '函数', '极限', '连续', '求导法则', '积分', '泰勒展开', '微分'];
    const status = [
      'learning',
      'good',
      'good',
      'learning',
      'learning',
      'weak',
      'learning',
      'learning',
    ];
    final nodes = [
      KnowledgeMapNode(
        id: 'course-calculus',
        name: course,
        course: course,
        category: 'course',
        weight: 0,
        external: false,
        hasRecord: false,
        status: 'course',
        needsReview: false,
        practiceCount: 0,
        evidenceCount: 0,
        weakPrerequisiteCount: 0,
        level: 0,
        nodeType: 'course',
      ),
      for (var index = 0; index < names.length; index++)
        KnowledgeMapNode(
          id: 'node-$index',
          name: names[index],
          course: course,
          category: 'calculus',
          weight: 1,
          external: false,
          hasRecord: true,
          masteryLevel: index == 0 ? 78 : 60 + index.toDouble(),
          status: status[index],
          needsReview: status[index] == 'weak',
          practiceCount: 8,
          evidenceCount: 6,
          weakPrerequisiteCount: 0,
          level: index == 0 ? 1 : 2,
        ),
    ];
    return KnowledgeMapData(
      course: course,
      nodes: nodes,
      edges: [
        const KnowledgeMapEdge(
          from: 'course-calculus',
          to: 'node-0',
          type: 'course_root',
        ),
        for (var index = 2; index < nodes.length; index++)
          KnowledgeMapEdge(
            from: 'node-0',
            to: nodes[index].id,
            type: 'related',
          ),
      ],
    );
  }

  @override
  Future<List<ResearchProject>> listResearchProjects() async => [project];

  @override
  Future<List<FrontierTrackingJob>> listFrontierJobs(
    String projectId,
  ) async => const [
    FrontierTrackingJob(
      id: 'paper-1',
      query:
          'Multimodal MRI and Cognitive Feature Learning for MCI Identification',
      status: 'succeeded',
    ),
    FrontierTrackingJob(
      id: 'paper-2',
      query: 'Graph Neural Network for Multi-site MCI Classification',
      status: 'succeeded',
    ),
  ];

  @override
  Future<List<ResearchDocument>> listResearchDocuments(
    String projectId,
  ) async => const [
    ResearchDocument(
      id: 'doc-1',
      title: 'MCI 多模态识别项目计划',
      type: 'paper',
      content: '',
      version: 1,
    ),
    ResearchDocument(
      id: 'doc-2',
      title: '数据预处理脚本_v2',
      type: 'notes',
      content: '',
      version: 2,
    ),
  ];

  @override
  Future<List<ResearchDataset>> listResearchDatasets(String projectId) async =>
      const [
        ResearchDataset(
          id: 'data-1',
          name: 'ADNI 1/2/3 MRI',
          filename: 'adni.csv',
          rowCount: 1842,
          columnCount: 24,
          profile: {},
        ),
        ResearchDataset(
          id: 'data-2',
          name: 'ADNI FDG-PET',
          filename: 'pet.csv',
          rowCount: 2105,
          columnCount: 18,
          profile: {},
        ),
      ];
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() async {
    final textLoader = FontLoader('NotoSansSC')
      ..addFont(rootBundle.load('assets/fonts/NotoSansSC-Variable.ttf'));
    final iconLoader = FontLoader('packages/lucide_icons_flutter/Lucide')
      ..addFont(
        rootBundle.load('packages/lucide_icons_flutter/assets/lucide.ttf'),
      );
    await Future.wait([textLoader.load(), iconLoader.load()]);
  });

  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<AppState> pumpShell(
    WidgetTester tester, {
    required Size size,
    bool conversation = false,
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _VisualApi(withConversation: conversation)
      ..sessionId = 'visual'
      ..userId = 'student'
      ..username = '同学';
    final state = AppState(api: api);
    addTearDown(state.dispose);
    if (conversation) {
      await state.loadConversations();
      await state.setActive('chat');
    } else {
      state
        ..learningCourses = const [
          LearningCourseSummary(
            name: '数据结构与算法',
            totalPoints: 12,
            evaluatedPoints: 8,
            weakPoints: 2,
            reviewPoints: 1,
            averageMastery: 51,
          ),
        ]
        ..masteryReport = const MasteryReport(
          totalPoints: 12,
          averageMastery: 51,
          weakPoints: [MasteryPoint(name: 'Dijkstra', masteryLevel: 42)],
          strongPoints: [],
          stalePoints: [],
        )
        ..userStats = const UserStats(learningStreakDays: 6)
        ..conversations.addAll([
          ChatConversation(
            id: 'recent-1',
            title: '最短路径算法对比（Dijkstra vs Bellman-Ford）',
            updatedAt: DateTime(2026, 9, 2, 14, 20),
          ),
          ChatConversation(
            id: 'recent-2',
            title: '图的存储结构（邻接表 vs 邻接矩阵）',
            updatedAt: DateTime(2026, 9, 1, 21, 15),
          ),
        ]);
    }
    await tester.pumpWidget(
      RepaintBoundary(
        key: const ValueKey('audit-capture'),
        child: AppScope(
          state: state,
          child: MaterialApp(
            debugShowCheckedModeBanner: false,
            theme: esaTheme(brightness: Brightness.dark),
            home: const HomeShell(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    return state;
  }

  Future<void> capture(WidgetTester tester, String path) => expectLater(
    find.byKey(const ValueKey('audit-capture')),
    matchesGoldenFile(path),
  );

  testWidgets('desktop landing', (tester) async {
    await pumpShell(tester, size: const Size(1440, 900));
    await capture(tester, '.audit-landing-desktop.png');
  });

  testWidgets('mobile landing', (tester) async {
    await pumpShell(tester, size: const Size(390, 844));
    await capture(tester, '.audit-landing-mobile.png');
  });

  testWidgets('large mobile landing', (tester) async {
    await pumpShell(tester, size: const Size(430, 932));
    await capture(tester, '.audit-landing-mobile-large.png');
  });

  testWidgets('desktop conversation', (tester) async {
    await pumpShell(tester, size: const Size(1440, 900), conversation: true);
    await capture(tester, '.audit-conversation-desktop.png');
  });

  testWidgets('mobile conversation', (tester) async {
    await pumpShell(tester, size: const Size(390, 844), conversation: true);
    await capture(tester, '.audit-conversation-mobile.png');
  });

  testWidgets('desktop knowledge map', (tester) async {
    await pumpShell(tester, size: const Size(1440, 900));
    await tester.tap(find.byTooltip('知识地图'));
    await tester.pumpAndSettle();
    await capture(tester, '.audit-knowledge-desktop.png');
  });

  testWidgets('mobile knowledge map', (tester) async {
    await pumpShell(tester, size: const Size(390, 844));
    await tester.tap(find.text('知识'));
    await tester.pumpAndSettle();
    await capture(tester, '.audit-knowledge-mobile.png');
  });

  testWidgets('mobile schedule workspace', (tester) async {
    await pumpShell(tester, size: const Size(390, 844));
    await tester.tap(find.text('日程'));
    await tester.pumpAndSettle();
    await capture(tester, '.audit-schedule-mobile.png');
  });

  testWidgets('mobile research workspace', (tester) async {
    await pumpShell(tester, size: const Size(390, 844));
    await tester.tap(
      find.byKey(const ValueKey('student-research-destination')),
    );
    await tester.pumpAndSettle();
    await capture(tester, '.audit-research-workspace-mobile.png');
  });

  testWidgets('desktop research project', (tester) async {
    await pumpShell(tester, size: const Size(1440, 900));
    await tester.tap(find.byTooltip('研究空间'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('科研项目'));
    await tester.pumpAndSettle();
    await tester.tap(find.text(_VisualApi.project.name).last);
    await tester.pumpAndSettle();
    await capture(tester, '.audit-research-desktop.png');
  });

  testWidgets('mobile research project', (tester) async {
    await pumpShell(tester, size: const Size(390, 844));
    await tester.tap(
      find.byKey(const ValueKey('student-research-destination')),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text(_VisualApi.project.name).last);
    await tester.pumpAndSettle();
    await capture(tester, '.audit-research-mobile.png');
  });
}
