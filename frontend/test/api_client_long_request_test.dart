import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  final operations = <String, Future<Object> Function(ApiClient)>{
    'chat': (api) => api.sendMessage('chat', 'question'),
    'attachments': (api) =>
        api.sendMessageWithAttachments('chat', 'question', ['file']),
    'task': (api) => api.sendTaskMessage('chat', 'question', 'summary'),
    'code': (api) =>
        api.executeCode('chat', code: 'print(1)', language: 'python'),
    'submission': (api) => api.analyzeTeachingSubmission('submission'),
    'assignment': (api) => api.analyzeTeachingAssignment('assignment'),
  };

  for (final entry in operations.entries) {
    testWidgets('${entry.key} uses the long-running timeout', (tester) async {
      final response = Completer<http.Response>();
      final client = MockClient((_) => response.future);
      final api = ApiClient(
        baseUrl: 'http://test.invalid',
        clientFactory: () => client,
      );
      var completed = false;
      Object? failure;
      final request = entry
          .value(api)
          .then<void>(
            (_) => completed = true,
            onError: (Object error) {
              completed = true;
              failure = error;
            },
          );
      await tester.pump(const Duration(seconds: 31));
      expect(completed, isFalse);
      final payload = ['chat', 'attachments', 'task'].contains(entry.key)
          ? '[]'
          : '{}';
      response.complete(http.Response(payload, 200));
      await tester.pump();
      await request;
      expect(failure, isNull);
      expect(completed, isTrue);
    });
  }
}
