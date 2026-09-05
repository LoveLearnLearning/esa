import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _TrackingClient extends MockClient {
  _TrackingClient(super.handler);

  bool closed = false;

  @override
  void close() {
    closed = true;
    super.close();
  }
}

void main() {
  test('default API endpoint never exposes the backend HTTP address', () {
    final baseUrl = ApiClient().baseUrl;

    expect(baseUrl, kIsWeb ? '/api' : 'https://esa.lovelearnlearning.cn/api');
    expect(baseUrl, isNot(contains('115.29.197.244')));
    expect(baseUrl, isNot(startsWith('http://')));
  });

  test('explicit API endpoint has its trailing slash normalized', () {
    expect(
      ApiClient(baseUrl: 'https://example.com/api/').baseUrl,
      'https://example.com/api',
    );
  });

  test('ordinary REST requests convert timeouts to ApiException', () async {
    final response = Completer<http.Response>();
    final client = _TrackingClient((_) => response.future);
    final api = ApiClient(
      baseUrl: 'http://test.invalid',
      clientFactory: () => client,
      requestTimeout: Duration.zero,
    );

    await expectLater(
      api.listConversations(),
      throwsA(
        isA<ApiException>()
            .having((error) => error.statusCode, 'statusCode', 0)
            .having((error) => error.detail, 'detail', '请求超时，请稍后重试'),
      ),
    );
    expect(client.closed, isTrue);
    response.complete(http.Response('[]', 200));
  });

  test(
    'REST clients close after success, HTTP error and network error',
    () async {
      for (final status in [200, 503, 0]) {
        final client = _TrackingClient((_) async {
          if (status == 0) throw http.ClientException('connection lost');
          return http.Response(
            status == 200 ? '[]' : '{"detail":"unavailable"}',
            status,
          );
        });
        final api = ApiClient(
          baseUrl: 'http://test.invalid',
          clientFactory: () => client,
        );
        if (status == 200) {
          expect(await api.listConversations(), isEmpty);
        } else {
          await expectLater(
            api.listConversations(),
            throwsA(isA<ApiException>()),
          );
        }
        expect(client.closed, isTrue);
      }
    },
  );

  test('conversation title requests use the managed REST client', () async {
    final client = _TrackingClient((request) async {
      expect(request.method, 'GET');
      expect(request.url.path, '/conversations/history');
      expect(request.headers['Authorization'], 'Bearer session');
      return http.Response(
        jsonEncode({
          'conversation_id': 'history',
          'title': 'Saved title',
          'updated_at': '2026-09-05T00:00:00Z',
        }),
        200,
      );
    });
    final api = ApiClient(
      baseUrl: 'http://test.invalid',
      clientFactory: () => client,
    )..sessionId = 'session';

    final conversation = await api.getConversation('history');

    expect(conversation.title, 'Saved title');
    expect(client.closed, isTrue);
  });

  test('a delayed logout cannot erase a newer login', () async {
    final response = Completer<http.Response>();
    final client = _TrackingClient((request) {
      expect(request.headers['Authorization'], 'Bearer old-session');
      return response.future;
    });
    final api = ApiClient(
      baseUrl: 'http://test.invalid',
      clientFactory: () => client,
    )..sessionId = 'old-session';

    final logout = api.logout();
    api.sessionId = 'new-session';
    api.userId = 'new-user';
    response.complete(http.Response('{}', 200));
    await logout;

    expect(api.sessionId, 'new-session');
    expect(api.userId, 'new-user');
    expect(client.closed, isTrue);
  });

  test('public source preview resolves a web-relative URL through /api', () {
    final api = ApiClient(baseUrl: '/api');

    final target = api.resolveSourcePreviewUri(
      '/knowledge-base/public/documents/doc-1/content',
      pageUri: Uri.parse('https://www.lovelearnlearning.cn/esa/'),
    );

    expect(
      target,
      Uri.parse(
        'https://www.lovelearnlearning.cn/api/'
        'knowledge-base/public/documents/doc-1/content',
      ),
    );
  });

  test('public source preview does not duplicate an existing /api prefix', () {
    final api = ApiClient(baseUrl: '/api');

    final target = api.resolveSourcePreviewUri(
      '/api/knowledge-base/public/documents/doc-1/content',
      pageUri: Uri.parse('https://www.lovelearnlearning.cn/esa/'),
    );

    expect(
      target,
      Uri.parse(
        'https://www.lovelearnlearning.cn/api/'
        'knowledge-base/public/documents/doc-1/content',
      ),
    );
  });

  test('public source preview rejects a cross-origin URL', () {
    final api = ApiClient(baseUrl: 'https://www.lovelearnlearning.cn/api');

    expect(
      () => api.resolveSourcePreviewUri('https://example.com/source.pdf'),
      throwsA(
        isA<ApiException>().having(
          (error) => error.detail,
          'detail',
          '来源地址不受信任',
        ),
      ),
    );
  });

  test('message request sends the selected knowledge sources', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(server.close);
    late Map<String, dynamic> requestBody;
    final handled = server.first.then((request) async {
      requestBody =
          jsonDecode(await utf8.decoder.bind(request).join())
              as Map<String, dynamic>;
      request.response
        ..statusCode = HttpStatus.ok
        ..headers.contentType = ContentType.json
        ..write('[]');
      await request.response.close();
    });
    final api = ApiClient(
      baseUrl: 'http://${server.address.host}:${server.port}/api',
    );

    await api.sendMessageWithAttachments(
      'conversation-1',
      '只查个人资料',
      const [],
      knowledgeSources: const {KnowledgeSource.personal},
      personalKnowledgeBaseId: 'personal-kb-a',
    );
    await handled;

    expect(requestBody['attachment_ids'], isEmpty);
    expect(requestBody['knowledge_sources'], ['personal']);
    expect(requestBody['personal_knowledge_base_id'], 'personal-kb-a');
  });

  test('task-mode request keeps the selected knowledge sources', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(server.close);
    late Map<String, dynamic> requestBody;
    final handled = server.first.then((request) async {
      requestBody =
          jsonDecode(await utf8.decoder.bind(request).join())
              as Map<String, dynamic>;
      request.response
        ..statusCode = HttpStatus.ok
        ..headers.contentType = ContentType.json
        ..write('[]');
      await request.response.close();
    });
    final api = ApiClient(
      baseUrl: 'http://${server.address.host}:${server.port}/api',
    );

    await api.sendTaskMessage(
      'conversation-1',
      '解释这段材料',
      'concept',
      attachmentIds: const ['attachment-1'],
      knowledgeSources: const {KnowledgeSource.public},
    );
    await handled;

    expect(requestBody['task_mode'], 'concept');
    expect(requestBody['attachment_ids'], ['attachment-1']);
    expect(requestBody['knowledge_sources'], ['public']);
    expect(requestBody, isNot(contains('personal_knowledge_base_id')));
  });

  test(
    'stream message preserves a string detail from a 503 response',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(server.close);
      final handled = server.first.then((request) async {
        request.response
          ..statusCode = HttpStatus.serviceUnavailable
          ..headers.contentType = ContentType.json
          ..write(jsonEncode({'detail': '所选知识库服务暂不可用：公共知识库'}));
        await request.response.close();
      });
      final api = ApiClient(
        baseUrl: 'http://${server.address.host}:${server.port}/api',
      );

      await expectLater(
        api.streamMessage('conversation-1', '问题').drain<void>(),
        throwsA(
          isA<ApiException>()
              .having((error) => error.statusCode, 'statusCode', 503)
              .having((error) => error.detail, 'detail', '所选知识库服务暂不可用：公共知识库'),
        ),
      );
      await handled;
    },
  );
}
