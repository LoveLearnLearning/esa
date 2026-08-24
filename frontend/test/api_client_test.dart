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
    );
    await handled;

    expect(requestBody['attachment_ids'], isEmpty);
    expect(requestBody['knowledge_sources'], ['personal']);
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
  });
}
