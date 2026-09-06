import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/pages/knowledge_map_page.dart';
import 'package:frontend/state/app_state.dart';
import 'package:frontend/theme/esa_theme.dart';
import 'package:frontend/widgets/learning/knowledge_graph_canvas.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _RacingKnowledgeApi extends ApiClient {
  _RacingKnowledgeApi() : super(baseUrl: 'http://test.invalid');

  final List<Completer<KnowledgeMapData>> requests = [];

  @override
  Future<KnowledgeMapData> getKnowledgeMap(String course) {
    final request = Completer<KnowledgeMapData>();
    requests.add(request);
    return request.future;
  }
}

class _KnowledgeApi extends ApiClient {
  _KnowledgeApi() : super(baseUrl: 'http://test.invalid');

  int createdConversations = 0;
  int courseRequests = 0;
  int mapRequests = 0;
  final List<String> streamedInputs = [];

  @override
  Future<ChatConversation> createConversation({String? groupId}) async {
    createdConversations++;
    return ChatConversation(
      id: 'conversation-$createdConversations',
      title: '新对话',
      updatedAt: DateTime(2026),
      groupId: groupId,
    );
  }

  @override
  Future<void> renameConversation(String id, String title) async {}

  @override
  Stream<ChatStreamEvent> streamMessage(
    String id,
    String content, {
    String? personalKnowledgeBaseId,
  }) async* {
    streamedInputs.add(content);
    yield const ChatStreamEvent('start', {});
    yield const ChatStreamEvent('done', {});
  }

  @override
  Future<List<LearningCourseSummary>> getLearningCourses() async {
    courseRequests++;
    return const [
      LearningCourseSummary(
        name: '数据结构',
        totalPoints: 2,
        evaluatedPoints: 1,
        weakPoints: 1,
        reviewPoints: 1,
        averageMastery: 32,
      ),
    ];
  }

  @override
  Future<KnowledgeMapData> getKnowledgeMap(String course) async {
    mapRequests++;
    return const KnowledgeMapData(
      course: '数据结构',
      nodes: [
        KnowledgeMapNode(
          id: 'course-data-structures',
          name: '数据结构',
          course: '数据结构',
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
        KnowledgeMapNode(
          id: 'recursion',
          name: '递归',
          course: '数据结构',
          category: 'base',
          weight: 0.7,
          external: false,
          hasRecord: false,
          status: 'unseen',
          needsReview: false,
          practiceCount: 0,
          evidenceCount: 0,
          weakPrerequisiteCount: 0,
          level: 1,
        ),
        KnowledgeMapNode(
          id: 'tree',
          name: '二叉树遍历',
          course: '数据结构',
          category: 'tree',
          weight: 0.9,
          external: false,
          hasRecord: true,
          masteryLevel: 32,
          status: 'weak',
          retention: 0.5,
          evidenceConfidence: 0.8,
          needsReview: true,
          practiceCount: 3,
          evidenceCount: 3,
          weakPrerequisiteCount: 1,
          level: 2,
        ),
      ],
      edges: [
        KnowledgeMapEdge(
          from: 'course-data-structures',
          to: 'recursion',
          type: 'course_root',
        ),
        KnowledgeMapEdge(from: 'recursion', to: 'tree', type: 'prerequisite'),
      ],
    );
  }

  @override
  Future<KnowledgePointDetail> getKnowledgePointDetail(String kpId) async =>
      const KnowledgePointDetail(
        raw: {
          'point': {'id': 'tree', 'name': '二叉树遍历', 'course': '数据结构'},
          'state': {
            'mastery_level': 32,
            'retention': 0.5,
            'evidence_confidence': 0.8,
            'practice_count': 3,
          },
          'evidence_summary': {'evidence_count': 3, 'correct_rate': 0.33},
          'weak_prerequisites': [
            {'kp_id': 'recursion', 'name': '递归', 'mastery_level': 20},
          ],
        },
      );
}

class _EmptyKnowledgeApi extends ApiClient {
  _EmptyKnowledgeApi() : super(baseUrl: 'http://test.invalid');

  @override
  Future<List<LearningCourseSummary>> getLearningCourses() async => const [];
}

class _UnsupportedKnowledgeApi extends ApiClient {
  _UnsupportedKnowledgeApi() : super(baseUrl: 'http://test.invalid');

  @override
  Future<List<LearningCourseSummary>> getLearningCourses() async => const [
    LearningCourseSummary(
      name: '日语口语训练',
      totalPoints: 0,
      evaluatedPoints: 0,
      weakPoints: 0,
      reviewPoints: 0,
      supported: false,
      source: 'timetable',
    ),
  ];
}

class _UnassessedKnowledgeApi extends _KnowledgeApi {
  @override
  Future<List<LearningCourseSummary>> getLearningCourses() async => const [
    LearningCourseSummary(
      name: '数据结构',
      canonicalCourse: '数据结构',
      totalPoints: 2,
      evaluatedPoints: 0,
      weakPoints: 0,
      reviewPoints: 0,
    ),
  ];
}

class _BindableKnowledgeApi extends _KnowledgeApi {
  bool bound = false;

  @override
  Future<List<LearningCourseSummary>> getLearningCourses() async => [
    LearningCourseSummary(
      name: '数字电路技术',
      canonicalCourse: bound ? '数字逻辑与数字电路' : null,
      totalPoints: bound ? 2 : 0,
      evaluatedPoints: 0,
      weakPoints: 0,
      reviewPoints: 0,
      supported: bound,
      source: 'timetable',
    ),
  ];

  @override
  Future<List<LearningCourseCatalogItem>> getLearningCourseCatalog({
    String query = '',
  }) async => const [
    LearningCourseCatalogItem(name: '数字逻辑与数字电路', added: false),
  ];

  @override
  Future<void> bindLearningCourse({
    required String name,
    required String canonicalCourse,
  }) async {
    if (name == '数字电路技术' && canonicalCourse == '数字逻辑与数字电路') {
      bound = true;
    }
  }
}

class _SyncKnowledgeApi extends _KnowledgeApi {
  bool added = false;
  List<String> syncedNames = const [];

  @override
  Future<List<LearningCourseSummary>> getLearningCourses() async => added
      ? const [
          LearningCourseSummary(
            name: '数据结构',
            canonicalCourse: '数据结构',
            totalPoints: 2,
            evaluatedPoints: 0,
            weakPoints: 0,
            reviewPoints: 0,
            source: 'timetable',
          ),
        ]
      : const [];

  @override
  Future<void> addLearningCourses(
    Iterable<String> names, {
    required String source,
  }) async {
    syncedNames = names.toList();
    added = true;
  }
}

Future<void> _pumpPage(WidgetTester tester, ApiClient api) async {
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
        home: KnowledgeMapPage(onOpenChat: () {}, api: api),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void _useDesktopViewport(WidgetTester tester) {
  tester.view.physicalSize = const Size(1440, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('reuses overview courses and cached graph when reopening', (
    tester,
  ) async {
    _useDesktopViewport(tester);
    final api = _KnowledgeApi()
      ..sessionId = 'session'
      ..userId = 'user'
      ..username = 'tester';
    final state = AppState(api: api)
      ..learningCourses = const [
        LearningCourseSummary(
          name: '数据结构',
          totalPoints: 2,
          evaluatedPoints: 1,
          weakPoints: 1,
          reviewPoints: 1,
          averageMastery: 32,
        ),
      ];
    addTearDown(state.dispose);

    Widget app(Widget home) => AppScope(
      state: state,
      child: MaterialApp(
        theme: esaTheme(brightness: Brightness.dark),
        home: home,
      ),
    );

    await tester.pumpWidget(app(KnowledgeMapPage(onOpenChat: () {})));
    await tester.pumpAndSettle();
    expect(api.courseRequests, 0);
    expect(api.mapRequests, 1);

    await tester.pumpWidget(app(const SizedBox.shrink()));
    await tester.pump();
    await tester.pumpWidget(app(KnowledgeMapPage(onOpenChat: () {})));
    await tester.pumpAndSettle();
    expect(api.courseRequests, 0);
    expect(api.mapRequests, 1);
  });

  test('old knowledge-map payloads gain a connected course node', () {
    final data = KnowledgeMapData.fromJson({
      'course': '数据结构',
      'nodes': [
        {'id': 'linear', 'name': '线性表', 'level': 0},
        {'id': 'tree', 'name': '树', 'level': 0},
        {'id': 'binary-tree', 'name': '二叉树', 'level': 1},
      ],
      'edges': [
        {'from': 'tree', 'to': 'binary-tree', 'type': 'prerequisite'},
      ],
    });

    final courseNode = data.nodes.singleWhere((node) => node.isCourse);
    expect(courseNode.name, '数据结构');
    expect(
      data.edges
          .where((edge) => edge.type == 'course_root')
          .map((edge) => edge.to)
          .toSet(),
      {'linear', 'tree'},
    );
  });

  testWidgets('loads graph, filters problems, and opens point detail', (
    tester,
  ) async {
    _useDesktopViewport(tester);
    final api = _KnowledgeApi()
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
          home: KnowledgeMapPage(onOpenChat: () {}, api: api),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('数据结构'), findsWidgets);
    expect(
      find.byKey(const ValueKey('knowledge-graph-node-course-data-structures')),
      findsOneWidget,
    );
    expect(find.text('递归'), findsOneWidget);
    expect(find.text('二叉树遍历'), findsOneWidget);

    await tester.tap(find.text('只看我的问题'));
    await tester.pumpAndSettle();
    expect(find.text('递归'), findsOneWidget);
    expect(find.text('二叉树遍历'), findsOneWidget);

    await tester.tap(find.text('二叉树遍历'));
    await tester.pumpAndSettle();
    expect(find.text('学习证据'), findsOneWidget);
    expect(find.text('薄弱前置'), findsOneWidget);
    expect(find.text('让 ESA 讲解'), findsOneWidget);
  });

  testWidgets('course node opens a course overview instead of point details', (
    tester,
  ) async {
    await _pumpPage(tester, _KnowledgeApi());

    await tester.tap(
      find.byKey(const ValueKey('knowledge-graph-node-course-data-structures')),
    );
    await tester.pumpAndSettle();

    expect(find.text('课程概览'), findsOneWidget);
    expect(find.text('2'), findsWidgets);
    expect(find.text('知识子树'), findsOneWidget);
  });

  testWidgets('supports editor layout controls and branch folding', (
    tester,
  ) async {
    _useDesktopViewport(tester);
    await _pumpPage(tester, _KnowledgeApi());

    expect(
      find.byKey(const ValueKey('knowledge-layout-horizontal')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('knowledge-layout-vertical')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('knowledge-auto-layout')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('knowledge-layout-vertical')));
    await tester.pumpAndSettle();
    final preferences = await SharedPreferences.getInstance();
    expect(
      preferences.getString('esa.knowledge_graph.数据结构.direction'),
      'vertical',
    );

    await tester.tap(
      find.byKey(const ValueKey('knowledge-collapse-recursion')),
    );
    await tester.pumpAndSettle();
    expect(find.text('递归'), findsOneWidget);
    expect(find.text('二叉树遍历'), findsNothing);
    expect(
      preferences.getStringList('esa.knowledge_graph.数据结构.collapsed'),
      contains('recursion'),
    );

    await tester.tap(
      find.byKey(const ValueKey('knowledge-collapse-recursion')),
    );
    await tester.pumpAndSettle();
    expect(find.text('二叉树遍历'), findsOneWidget);
  });

  testWidgets('renders only the selected tree edges instead of cross links', (
    tester,
  ) async {
    _useDesktopViewport(tester);
    const nodes = [
      KnowledgeMapNode(
        id: 'course',
        name: '课程',
        course: '测试课程',
        category: 'course',
        weight: 1,
        external: false,
        hasRecord: false,
        status: 'course',
        needsReview: false,
        practiceCount: 0,
        evidenceCount: 0,
        weakPrerequisiteCount: 0,
        level: 0,
      ),
      KnowledgeMapNode(
        id: 'a',
        name: '知识点 A',
        course: '测试课程',
        category: 'topic',
        weight: 1,
        external: false,
        hasRecord: false,
        status: 'learning',
        needsReview: false,
        practiceCount: 0,
        evidenceCount: 0,
        weakPrerequisiteCount: 0,
        level: 1,
      ),
      KnowledgeMapNode(
        id: 'b',
        name: '知识点 B',
        course: '测试课程',
        category: 'topic',
        weight: 1,
        external: false,
        hasRecord: false,
        status: 'unseen',
        needsReview: false,
        practiceCount: 0,
        evidenceCount: 0,
        weakPrerequisiteCount: 0,
        level: 2,
      ),
    ];
    const edges = [
      KnowledgeMapEdge(from: 'course', to: 'a', type: 'course_root'),
      KnowledgeMapEdge(from: 'a', to: 'b', type: 'prerequisite'),
      KnowledgeMapEdge(from: 'course', to: 'b', type: 'cross_link'),
    ];

    await tester.pumpWidget(
      MaterialApp(
        theme: esaTheme(brightness: Brightness.dark),
        home: Scaffold(
          body: KnowledgeGraphCanvas(
            visibleNodes: nodes,
            edges: edges,
            onNodeTap: (_) {},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('knowledge-tree-edge-count-2')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('knowledge-tree-edge-count-3')),
      findsNothing,
    );
  });

  testWidgets('从知识点开始学习会建立独立新对话', (tester) async {
    _useDesktopViewport(tester);
    final api = _KnowledgeApi()
      ..sessionId = 'session'
      ..userId = 'user'
      ..username = 'tester';
    final state = AppState(api: api);
    addTearDown(state.dispose);
    await state.send('原对话的问题');
    expect(api.createdConversations, 1);
    var openedChat = false;

    await tester.pumpWidget(
      AppScope(
        state: state,
        child: MaterialApp(
          theme: esaTheme(brightness: Brightness.dark),
          home: KnowledgeMapPage(onOpenChat: () => openedChat = true, api: api),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('二叉树遍历'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('让 ESA 讲解'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('让 ESA 讲解'));
    await tester.pumpAndSettle();

    expect(openedChat, isTrue);
    expect(api.createdConversations, 2);
    expect(state.activeId, 'conversation-2');
    expect(api.streamedInputs.last, contains('二叉树遍历'));
  });

  testWidgets('shows onboarding instead of Not Found when no courses exist', (
    tester,
  ) async {
    await _pumpPage(tester, _EmptyKnowledgeApi());

    expect(find.text('建立你的个人知识地图'), findsOneWidget);
    expect(find.text('从课表添加课程'), findsWidgets);
    expect(find.text('手动添加课程'), findsOneWidget);
    expect(find.textContaining('Not Found'), findsNothing);
    expect(find.text('全部状态'), findsNothing);
  });

  testWidgets('shows a dedicated unsupported-course state', (tester) async {
    await _pumpPage(tester, _UnsupportedKnowledgeApi());

    expect(find.text('这门课程暂时没有可用的知识地图'), findsOneWidget);
    expect(find.textContaining('日语口语训练'), findsWidgets);
    expect(find.text('匹配已有课程'), findsOneWidget);
    expect(find.textContaining('Not Found'), findsNothing);
  });

  testWidgets('renders the graph and an unassessed banner without records', (
    tester,
  ) async {
    await _pumpPage(tester, _UnassessedKnowledgeApi());

    expect(find.textContaining('你的知识地图已经建立'), findsOneWidget);
    expect(find.text('递归'), findsOneWidget);
    expect(find.text('二叉树遍历'), findsOneWidget);
  });

  testWidgets('syncs selected timetable courses into the learning space', (
    tester,
  ) async {
    final api = _SyncKnowledgeApi()
      ..sessionId = 'session'
      ..userId = 'user'
      ..username = 'tester';
    final state = AppState(api: api)
      ..scheduleLoaded = true
      ..scheduleCourses.add(
        const ScheduleCourse(
          id: 'course-1',
          name: '数据结构',
          weekday: 1,
          startPeriod: 1,
          endPeriod: 2,
          startWeek: 1,
          endWeek: 18,
          colorValue: 0xFF2563EB,
        ),
      );
    addTearDown(state.dispose);
    await tester.pumpWidget(
      AppScope(
        state: state,
        child: MaterialApp(
          theme: esaTheme(brightness: Brightness.dark),
          home: KnowledgeMapPage(onOpenChat: () {}, api: api),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('从课表添加课程'));
    await tester.pumpAndSettle();
    expect(find.text('从课表添加课程'), findsWidgets);
    expect(find.text('数据结构'), findsOneWidget);

    await tester.tap(find.text('添加 1 门课程'));
    await tester.pumpAndSettle();

    expect(api.syncedNames, ['数据结构']);
    expect(find.text('递归'), findsOneWidget);
  });

  testWidgets('lets an unsupported timetable name bind to a canonical course', (
    tester,
  ) async {
    final api = _BindableKnowledgeApi();
    await _pumpPage(tester, api);

    await tester.tap(find.text('匹配已有课程'));
    await tester.pumpAndSettle();
    expect(find.text('数字逻辑与数字电路'), findsOneWidget);

    await tester.tap(find.text('数字逻辑与数字电路'));
    await tester.pumpAndSettle();

    expect(api.bound, isTrue);
    expect(find.text('递归'), findsOneWidget);
  });

  test('does not let an older refresh overwrite the newest map', () async {
    final api = _RacingKnowledgeApi()
      ..sessionId = 'session-a'
      ..userId = 'user-a';
    final state = AppState(api: api);
    addTearDown(state.dispose);

    final older = state.loadKnowledgeMap('数据结构');
    final newer = state.loadKnowledgeMap('数据结构', forceRefresh: true);
    expect(api.requests, hasLength(2));

    api.requests[1].complete(
      const KnowledgeMapData(course: 'newest', nodes: [], edges: []),
    );
    await newer;
    api.requests[0].complete(
      const KnowledgeMapData(course: 'older', nodes: [], edges: []),
    );
    await older;

    expect(state.cachedKnowledgeMap('数据结构')?.course, 'newest');
  });
}
