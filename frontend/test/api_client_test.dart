import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';

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
