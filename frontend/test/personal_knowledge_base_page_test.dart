import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/pages/personal_knowledge_base_page.dart';
import 'package:frontend/state/app_state.dart';
import 'package:frontend/theme/esa_theme.dart';

class _KnowledgeBaseApi extends ApiClient {
  _KnowledgeBaseApi() : super(baseUrl: 'http://test.invalid');

  final snapshot = PersonalKnowledgeBase(
    fileCount: 2,
    chunkCount: 48,
    indexCount: 48,
    status: KnowledgeBaseBuildStatus.ready,
    progress: 1,
    files: [
      KnowledgeBaseFile(
        id: 'file-1',
        filename: '数据结构笔记.md',
        mediaType: 'text/markdown',
        sizeBytes: 2048,
        status: KnowledgeBaseBuildStatus.ready,
        progress: 1,
        chunkCount: 20,
        indexCount: 20,
        uploadedAt: DateTime(2026, 8, 21),
      ),
      KnowledgeBaseFile(
        id: 'file-2',
        filename: '图算法讲义.pdf',
        mediaType: 'application/pdf',
        sizeBytes: 4 * 1024 * 1024,
        status: KnowledgeBaseBuildStatus.ready,
        progress: 1,
        chunkCount: 28,
        indexCount: 28,
        uploadedAt: DateTime(2026, 8, 21),
      ),
    ],
  );

  @override
  Future<PersonalKnowledgeBase> getPersonalKnowledgeBase() async => snapshot;

  @override
  Future<AttachmentContent> fetchPersonalKnowledgeBaseFile(
    KnowledgeBaseFile file,
  ) async => AttachmentContent(
    bytes: Uint8List.fromList(utf8.encode('图的最短路径与 Dijkstra')),
    mediaType: 'text/markdown',
    filename: file.filename,
  );
}

void main() {
  testWidgets('shows knowledge-base metrics, files and selected preview', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final api = _KnowledgeBaseApi()
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
          home: const Scaffold(body: PersonalKnowledgeBasePage()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('个人知识库'), findsOneWidget);
    expect(find.text('2'), findsWidgets);
    expect(find.text('48'), findsNWidgets(2));
    expect(
      find.byKey(const ValueKey('knowledge-base-progress')),
      findsOneWidget,
    );
    expect(find.text('数据结构笔记.md'), findsOneWidget);
    expect(find.text('图算法讲义.pdf'), findsOneWidget);
    expect(find.text('选择左侧文件进行预览'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('knowledge-file-file-1')));
    await tester.pumpAndSettle();

    expect(find.text('图的最短路径与 Dijkstra'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('mobile switches from file list to preview and back', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final api = _KnowledgeBaseApi()
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
          home: const Scaffold(body: PersonalKnowledgeBasePage()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('knowledge-file-file-1')));
    await tester.pumpAndSettle();
    expect(find.text('返回文件列表'), findsOneWidget);
    expect(find.text('图的最短路径与 Dijkstra'), findsOneWidget);

    await tester.tap(find.text('返回文件列表'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('knowledge-base-search')), findsOneWidget);
  });
}
