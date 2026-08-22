import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/pages/personal_knowledge_base_page.dart';
import 'package:frontend/state/app_state.dart';
import 'package:frontend/theme/esa_theme.dart';
import 'package:frontend/widgets/attachment_preview/pdf_attachment_viewer.dart';

class _KnowledgeBaseApi extends ApiClient {
  _KnowledgeBaseApi() : super(baseUrl: 'http://test.invalid');

  int previewRequests = 0;
  int cancelledPreviewRequests = 0;
  Duration previewDelay = Duration.zero;
  final Map<String, String> previewMediaTypes = {};

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
  Future<AttachmentContent> fetchPersonalKnowledgeBasePreview(
    KnowledgeBaseFile file, {
    RequestCancellation? cancellation,
  }) async {
    previewRequests += 1;
    if (previewDelay > Duration.zero) {
      cancellation?.attach(() => cancelledPreviewRequests += 1);
      await Future<void>.delayed(previewDelay);
      cancellation?.detach();
      if (cancellation?.isCancelled ?? false) {
        throw ApiException(0, 'cancelled');
      }
    }
    final mediaType = previewMediaTypes[file.id] ?? 'text/plain; charset=utf-8';
    final bytes = switch (mediaType) {
      'application/pdf' => Uint8List.fromList(utf8.encode('%PDF-1.4\n%%EOF\n')),
      'image/png' => base64Decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
      ),
      _ => Uint8List.fromList(utf8.encode('preview for ${file.filename}')),
    };
    return AttachmentContent(
      bytes: bytes,
      mediaType: mediaType,
      filename: '${file.filename}.preview.txt',
    );
  }
}

void main() {
  test('parses every backend knowledge-base build status', () {
    const expected = {
      'queued': KnowledgeBaseBuildStatus.queued,
      'building': KnowledgeBaseBuildStatus.building,
      'ready': KnowledgeBaseBuildStatus.ready,
      'failed': KnowledgeBaseBuildStatus.failed,
    };
    for (final entry in expected.entries) {
      final snapshot = PersonalKnowledgeBase.fromJson({
        'file_count': 1,
        'chunk_count': 2,
        'index_count': 2,
        'status': entry.key,
        'progress': 0.5,
        'files': [
          {
            'id': 'file-${entry.key}',
            'filename': 'notes.txt',
            'media_type': 'text/plain',
            'size_bytes': 12,
            'status': entry.key,
            'progress': 0.5,
            'chunk_count': 2,
            'index_count': 2,
          },
        ],
      });
      expect(snapshot.status, entry.value);
      expect(snapshot.files.single.status, entry.value);
    }
  });

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

    expect(find.text('preview for 数据结构笔记.md'), findsOneWidget);
    expect(api.previewRequests, 1);
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
    expect(find.text('preview for 数据结构笔记.md'), findsOneWidget);
    expect(api.previewRequests, 1);

    await tester.tap(find.text('返回文件列表'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('knowledge-base-search')), findsOneWidget);
  });

  testWidgets('switching files cancels and ignores the stale preview', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final api = _KnowledgeBaseApi()
      ..sessionId = 'session'
      ..userId = 'user'
      ..username = 'tester'
      ..previewDelay = const Duration(milliseconds: 50);
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
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('knowledge-file-file-2')));
    await tester.pump(const Duration(milliseconds: 100));

    expect(api.previewRequests, 2);
    expect(api.cancelledPreviewRequests, 1);
    expect(find.text('preview for 图算法讲义.pdf'), findsOneWidget);
    expect(find.text('preview for 数据结构笔记.md'), findsNothing);
    expect(
      find.byKey(const ValueKey('knowledge-base-derived-preview-label')),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('selects PDF and image previewers from response media type', (
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
    api.previewMediaTypes['file-2'] = 'application/pdf';
    api.previewMediaTypes['file-1'] = 'image/png';
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

    await tester.tap(find.byKey(const ValueKey('knowledge-file-file-2')));
    await tester.pumpAndSettle();
    expect(find.byType(PdfAttachmentViewer), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('knowledge-file-file-1')));
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('knowledge-base-image-preview')),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });
}
