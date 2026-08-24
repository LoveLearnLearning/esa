import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:http/http.dart' as http;

class _StreamingClient extends http.BaseClient {
  _StreamingClient(this.responder, this.onRequest);

  final http.StreamedResponse Function(http.BaseRequest request) responder;
  final void Function(http.BaseRequest request) onRequest;
  bool closed = false;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    onRequest(request);
    return responder(request);
  }

  @override
  void close() {
    closed = true;
    super.close();
  }
}

class _PendingClient extends http.BaseClient {
  final Completer<http.StreamedResponse> pending =
      Completer<http.StreamedResponse>();
  bool closed = false;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) =>
      pending.future;

  @override
  void close() {
    closed = true;
    if (!pending.isCompleted) {
      pending.completeError(http.ClientException('cancelled'));
    }
    super.close();
  }
}

KnowledgeBaseFile _file({int size = 200 * 1024 * 1024 - 1}) =>
    KnowledgeBaseFile(
      id: 'file-1',
      filename: 'large.pdf',
      mediaType: 'application/pdf',
      sizeBytes: size,
      status: KnowledgeBaseBuildStatus.ready,
      progress: 1,
      chunkCount: 1,
      indexCount: 1,
      uploadedAt: DateTime(2026),
    );

void main() {
  test('near-limit original content remains a cancellable stream', () async {
    final clients = <_StreamingClient>[];
    final paths = <String>[];
    final api = ApiClient(
      baseUrl: 'http://test.invalid/api',
      clientFactory: () {
        late _StreamingClient client;
        client = _StreamingClient(
          (request) => http.StreamedResponse(
            Stream<List<int>>.fromIterable([
              List<int>.filled(64 * 1024, 1),
              List<int>.filled(64 * 1024, 2),
            ]),
            206,
            headers: {
              'content-type': 'application/pdf',
              'content-length': '${128 * 1024}',
            },
            contentLength: 128 * 1024,
          ),
          (request) => paths.add(request.url.path),
        );
        clients.add(client);
        return client;
      },
    )..sessionId = 'session';

    final transfer = await api.fetchPersonalKnowledgeBaseFile(
      _file(),
      range: 'bytes=0-131071',
    );
    final chunks = await transfer.chunks.toList();

    expect(chunks.map((item) => item.length), [64 * 1024, 64 * 1024]);
    expect(paths.single, '/api/me/knowledge-base/files/file-1/content');
    expect(clients.single.closed, isTrue);
  });

  test(
    'oversized derived preview is rejected before its stream is read',
    () async {
      final clients = <_StreamingClient>[];
      var streamListened = false;
      final api =
          ApiClient(
              baseUrl: 'http://test.invalid/api',
              clientFactory: () {
                late _StreamingClient client;
                client = _StreamingClient(
                  (_) => http.StreamedResponse(
                    Stream<List<int>>.multi((controller) {
                      streamListened = true;
                      controller.close();
                    }),
                    200,
                    headers: {'content-type': 'application/pdf'},
                    contentLength: 9 * 1024 * 1024,
                  ),
                  (_) {},
                );
                clients.add(client);
                return client;
              },
            )
            ..sessionId = 'session'
            ..userId = 'user';

      await expectLater(
        api.fetchPersonalKnowledgeBasePreview(_file()),
        throwsA(
          isA<ApiException>().having(
            (error) => error.statusCode,
            'statusCode',
            413,
          ),
        ),
      );

      expect(streamListened, isFalse);
      expect(clients.single.closed, isTrue);
    },
  );

  test('bounded preview cache is reused and explicitly cleared', () async {
    var requests = 0;
    final clients = <_StreamingClient>[];
    final body = utf8.encode('bounded preview');
    final api =
        ApiClient(
            baseUrl: 'http://test.invalid/api',
            clientFactory: () {
              late _StreamingClient client;
              client = _StreamingClient(
                (_) => http.StreamedResponse(
                  Stream<List<int>>.value(body),
                  200,
                  headers: {'content-type': 'text/plain; charset=utf-8'},
                  contentLength: body.length,
                ),
                (_) => requests += 1,
              );
              clients.add(client);
              return client;
            },
          )
          ..sessionId = 'session'
          ..userId = 'user';

    final first = await api.fetchPersonalKnowledgeBasePreview(_file());
    final second = await api.fetchPersonalKnowledgeBasePreview(_file());
    expect(utf8.decode(first.bytes), 'bounded preview');
    expect(identical(first, second), isTrue);
    expect(requests, 1);

    api.clearPersonalKnowledgeBasePreviewCache();
    await api.fetchPersonalKnowledgeBasePreview(_file());
    expect(requests, 2);
    expect(clients.every((client) => client.closed), isTrue);
  });

  test(
    'cancellation closes a request before response headers arrive',
    () async {
      final client = _PendingClient();
      final cancellation = RequestCancellation();
      final api =
          ApiClient(
              baseUrl: 'http://test.invalid/api',
              clientFactory: () => client,
            )
            ..sessionId = 'session'
            ..userId = 'user';

      final pending = api.fetchPersonalKnowledgeBasePreview(
        _file(),
        cancellation: cancellation,
      );
      await Future<void>.delayed(Duration.zero);
      cancellation.cancel();

      await expectLater(
        pending,
        throwsA(
          isA<ApiException>().having(
            (error) => error.detail,
            'detail',
            contains('取消'),
          ),
        ),
      );
      expect(client.closed, isTrue);
    },
  );
}
